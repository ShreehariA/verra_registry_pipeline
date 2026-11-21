"""Where each layer's tables are kept: Parquet files, one partition per snapshot date.

The layout comes from the config, e.g. '{layer}/{table}/snapshot_date={date}/data.parquet'.
Re-running a date replaces exactly that partition and nothing else, which is
what makes re-runs idempotent. Every write goes to a temporary file that is
then renamed into place, so a crash never leaves half a file behind.

Stages depend on the `Lake` interface, not on `LocalLake`, so a Cloud Storage
lake can replace it without changing any stage.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Protocol

import pyarrow as pa
import pyarrow.parquet as pq

from verra_pipeline.errors import SchemaMismatchError
from verra_pipeline.schema.model import ColumnSpec, ColumnType

Cell = str | int | float | bool | date | None


@dataclass(frozen=True)
class TableData:
    """A table to store: the schema's columns, and rows of plain Python values in the same order."""

    columns: tuple[ColumnSpec, ...]
    rows: tuple[tuple[Cell, ...], ...]

    def column_names(self) -> tuple[str, ...]:
        return tuple(column.name for column in self.columns)


class Lake(Protocol):
    """Storage for layer tables and run manifests."""

    def write_table(self, layer: str, table: str, snapshot_date: date, data: TableData) -> str:
        """Store a table's partition for one snapshot and return where it went."""
        ...

    def write_manifest(self, stage: str, snapshot_date: date, document: Mapping[str, object]) -> str:
        """Store a stage's record of a run for one snapshot and return where it went."""
        ...


class LocalLake:
    """A lake in a folder on this machine."""

    def __init__(self, root: Path, table_file: str, manifest_file: str) -> None:
        self._root = root
        self._table_file = table_file
        self._manifest_file = manifest_file

    @property
    def root(self) -> Path:
        return self._root

    def table_file(self, layer: str, table: str, snapshot_date: date) -> Path:
        return self._root / self._table_file.format(layer=layer, table=table, date=snapshot_date.isoformat())

    def history_pattern(self, layer: str, table: str) -> Path:
        """A glob matching the table's partition for every snapshot."""
        return self._root / self._table_file.format(layer=layer, table=table, date="*")

    def manifest_file(self, stage: str, snapshot_date: date) -> Path:
        return self._root / self._manifest_file.format(stage=stage, date=snapshot_date.isoformat())

    def write_table(self, layer: str, table: str, snapshot_date: date, data: TableData) -> str:
        target = self.table_file(layer, table, snapshot_date)
        arrow_table = _to_arrow(data, f"{layer}.{table}")
        _replace_atomically(
            target, lambda temporary: _write_parquet(arrow_table, temporary, f"{layer}.{table}")
        )
        return self._relative(target)

    def write_manifest(self, stage: str, snapshot_date: date, document: Mapping[str, object]) -> str:
        target = self.manifest_file(stage, snapshot_date)
        text = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
        _replace_atomically(target, lambda temporary: temporary.write_text(text, encoding="utf-8"))
        return self._relative(target)

    def _relative(self, path: Path) -> str:
        """Paths are reported relative to the lake, so manifests read the same on any machine."""
        return path.relative_to(self._root).as_posix()


_ARROW_TYPES = {
    ColumnType.TEXT: pa.string(),
    ColumnType.INTEGER: pa.int64(),
    ColumnType.DOUBLE: pa.float64(),
    ColumnType.BOOLEAN: pa.bool_(),
    ColumnType.DATE: pa.date32(),
}


def _to_arrow(data: TableData, name: str) -> pa.Table:
    schema = pa.schema([pa.field(c.name, _ARROW_TYPES[c.type], nullable=c.nullable) for c in data.columns])
    try:
        arrays = [
            pa.array([row[position] for row in data.rows], type=field.type)
            for position, field in enumerate(schema)
        ]
    except (pa.ArrowInvalid, pa.ArrowTypeError) as error:
        raise SchemaMismatchError(f"{name}: a value does not fit its column's type: {error}") from error
    return pa.Table.from_arrays(arrays, schema=schema)


def _write_parquet(table: pa.Table, path: Path, name: str) -> None:
    try:
        pq.write_table(table, path)
    except pa.ArrowInvalid as error:
        raise SchemaMismatchError(f"{name}: {error}") from error


def _replace_atomically(target: Path, write: Callable[[Path], object]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp")
    try:
        write(temporary)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    temporary.replace(target)
