"""Load the schema folder: check every file, pull in shared column sets, and look tables up.

    <schema>/shared/<set>.json      column sets that several tables include
    <schema>/<layer>/<table>.json   one file per table, e.g. bronze/retirements.json

Each file is checked against its format (verra_pipeline/formats/) and then
against the other files. Any problem stops the run naming the file and the
reason, so a typo in a schema file can never silently change what is written.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Iterable, Mapping
from enum import Enum
from pathlib import Path
from typing import Any

from verra_pipeline.errors import SchemaDefinitionError
from verra_pipeline.json_formats import (
    COLUMN_SET_FORMAT,
    TABLE_FORMAT,
    check_format,
    format_document,
    read_json,
)
from verra_pipeline.schema.model import ColumnSpec, ColumnType, ForeignKey, SourceSpec, TableSpec

SHARED_FOLDER = "shared"
BRONZE = "bronze"
QUARANTINE_ROLE = "quarantine"


def layer_order() -> tuple[str, ...]:
    """The layers in data-flow order, as the table format lists them."""
    return tuple(format_document(TABLE_FORMAT)["properties"]["layer"]["enum"])


class SchemaRegistry:
    """Every table declared in the schema folder, already checked."""

    def __init__(self, tables: Iterable[TableSpec]) -> None:
        self._tables = {table.qualified_name: table for table in tables}

    @classmethod
    def load(cls, folder: Path) -> SchemaRegistry:
        return cls(_SchemaFolder(folder).tables())

    def table(self, layer: str, name: str) -> TableSpec:
        qualified = f"{layer}.{name}"
        if qualified not in self._tables:
            raise SchemaDefinitionError(f"the schema has no table {qualified}")
        return self._tables[qualified]

    def tables(self, layer: str | None = None) -> tuple[TableSpec, ...]:
        """The tables of one layer, or of every layer, in layer order and then by name."""
        order = layer_order()
        chosen = (table for table in self._tables.values() if layer in (None, table.layer))
        return tuple(sorted(chosen, key=lambda table: (order.index(table.layer), table.name)))

    def systems(self) -> tuple[str, ...]:
        """The source systems that bronze tables are loaded from."""
        return tuple(
            sorted({t.source.system for t in self.tables(BRONZE) if t.source is not None and _is_loaded(t)})
        )

    def sourced_tables(self, system: str) -> tuple[TableSpec, ...]:
        """The bronze tables loaded from one source system's files."""
        tables = tuple(table for table in self.tables(BRONZE) if _is_loaded(table, system))
        if not tables:
            raise SchemaDefinitionError(f"no bronze table is loaded from the source system {system!r}")
        return tables

    def quarantine_table(self, system: str) -> TableSpec:
        """The bronze table that receives a source system's unreadable records."""
        for table in self.tables(BRONZE):
            if table.role == QUARANTINE_ROLE and table.source is not None and table.source.system == system:
                return table
        raise SchemaDefinitionError(f"no bronze quarantine table for the source system {system!r}")

    def fingerprint(self) -> str:
        """A checksum of every table definition; manifests record it to show which schema made the data."""
        payload = [dataclasses.asdict(table) for table in self.tables()]
        text = json.dumps(payload, sort_keys=True, default=_plain)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()


class _SchemaFolder:
    """Reads one schema folder and checks every file in it."""

    def __init__(self, root: Path) -> None:
        if not root.is_dir():
            raise SchemaDefinitionError(f"the schema folder {root} does not exist")
        self._root = root

    def tables(self) -> list[TableSpec]:
        column_sets = self._column_sets()
        tables = [self._table(path, column_sets) for path in self._table_files()]
        _check_across_tables(tables)
        return tables

    def _column_sets(self) -> dict[str, tuple[ColumnSpec, ...]]:
        column_sets: dict[str, tuple[ColumnSpec, ...]] = {}
        for path in sorted((self._root / SHARED_FOLDER).glob("*.json")):
            document = self._checked(path, COLUMN_SET_FORMAT)
            _require(
                document["name"] == path.stem,
                f"{self._where(path)}: name is {document['name']!r} but the file is {path.name}",
            )
            column_sets[path.stem] = tuple(_column(column) for column in document["columns"])
        return column_sets

    def _table_files(self) -> list[Path]:
        return sorted(path for path in self._root.glob("*/*.json") if path.parent.name != SHARED_FOLDER)

    def _table(self, path: Path, column_sets: Mapping[str, tuple[ColumnSpec, ...]]) -> TableSpec:
        document = self._checked(path, TABLE_FORMAT)
        where = self._where(path)
        _require(
            document["layer"] == path.parent.name,
            f"{where}: layer is {document['layer']!r} but the file is in the folder {path.parent.name!r}",
        )
        _require(
            document["name"] == path.stem,
            f"{where}: name is {document['name']!r} but the file is {path.name}",
        )
        table = TableSpec(
            layer=document["layer"],
            name=document["name"],
            description=document["description"],
            columns=_own_and_included_columns(document, column_sets, where),
            grain=document.get("grain"),
            source=SourceSpec(**document["source"]) if "source" in document else None,
            role=document.get("role"),
            unknown_columns=document.get("unknown_columns", "keep"),
            primary_key=tuple(document.get("primary_key", ())),
            foreign_keys=tuple(_foreign_key(key) for key in document.get("foreign_keys", ())),
        )
        _check_table(table, where)
        return table

    def _checked(self, path: Path, format_name: str) -> Any:
        document = read_json(path, SchemaDefinitionError)
        check_format(document, format_name, self._where(path), SchemaDefinitionError)
        return document

    def _where(self, path: Path) -> str:
        return path.relative_to(self._root).as_posix()


def _column(document: Mapping[str, Any]) -> ColumnSpec:
    return ColumnSpec(
        name=document["name"],
        type=ColumnType(document["type"]),
        description=document["description"],
        nullable=document.get("nullable", True),
        required=document.get("required", False),
        source_header=document.get("source_header"),
        aliases=tuple(document.get("aliases", ())),
        generated=document.get("generated"),
    )


def _foreign_key(document: Mapping[str, Any]) -> ForeignKey:
    return ForeignKey(
        columns=tuple(document["columns"]),
        referenced_table=document["references"]["table"],
        referenced_columns=tuple(document["references"]["columns"]),
    )


def _own_and_included_columns(
    document: Mapping[str, Any], column_sets: Mapping[str, tuple[ColumnSpec, ...]], where: str
) -> tuple[ColumnSpec, ...]:
    columns = [_column(column) for column in document["columns"]]
    for name in document.get("include", ()):
        _require(
            name in column_sets, f"{where}: includes {name!r}, but there is no {SHARED_FOLDER}/{name}.json"
        )
        columns.extend(column_sets[name])
    return tuple(columns)


def _check_table(table: TableSpec, where: str) -> None:
    _check_unique_columns(table, where)
    _check_layer_rules(table, where)
    _check_each_header_feeds_one_column(table, where)
    _check_key_columns_exist(table, where)


def _check_unique_columns(table: TableSpec, where: str) -> None:
    names = table.column_names
    repeated = sorted({name for name in names if names.count(name) > 1})
    _require(
        not repeated,
        f"{where}: columns appear more than once (check the includes too): {', '.join(repeated)}",
    )


def _check_layer_rules(table: TableSpec, where: str) -> None:
    if table.layer == BRONZE:
        _check_bronze_rules(table, where)
        return
    _require(
        table.source is None and table.role is None, f"{where}: only bronze tables have a source or a role"
    )
    _require(table.unknown_columns == "keep", f"{where}: only bronze tables can drop unknown columns")
    from_files = [column.name for column in table.columns if column.is_from_source]
    _require(not from_files, f"{where}: only bronze tables read columns from files: {', '.join(from_files)}")


def _check_bronze_rules(table: TableSpec, where: str) -> None:
    _require(
        not table.primary_key and not table.foreign_keys,
        f"{where}: bronze keeps data as delivered, so it declares no keys",
    )
    _require(table.source is not None, f"{where}: a bronze table must name its source system")
    has_file = table.source is not None and table.source.file_prefix is not None
    _require(
        has_file != (table.role == QUARANTINE_ROLE),
        f"{where}: a bronze table has a file_prefix (loaded from a file) or is its system's quarantine",
    )
    unfilled = [column.name for column in table.columns if not (column.generated or column.is_from_source)]
    _require(
        not unfilled,
        f"{where}: nothing fills these columns (no source_header or generated): {', '.join(unfilled)}",
    )
    if not has_file:
        from_file = [column.name for column in table.columns if column.is_from_source]
        _require(
            not from_file, f"{where}: has no source file, yet these columns read one: {', '.join(from_file)}"
        )


def _check_each_header_feeds_one_column(table: TableSpec, where: str) -> None:
    claimed: dict[str, str] = {}
    for column in table.columns:
        for header in column.accepted_headers():
            owner = claimed.setdefault(header, column.name)
            _require(
                owner == column.name,
                f"{where}: the header {header!r} would feed both {owner} and {column.name}",
            )


def _check_key_columns_exist(table: TableSpec, where: str) -> None:
    names = set(table.column_names)
    keys = [*table.primary_key, *(column for key in table.foreign_keys for column in key.columns)]
    unknown = [column for column in keys if column not in names]
    _require(not unknown, f"{where}: key columns that are not in the table: {', '.join(unknown)}")


def _check_across_tables(tables: list[TableSpec]) -> None:
    by_name = {table.qualified_name: table for table in tables}
    for table in tables:
        for key in table.foreign_keys:
            target = by_name.get(key.referenced_table)
            if target is None:
                raise SchemaDefinitionError(
                    f"{table.qualified_name}: references {key.referenced_table}, which does not exist"
                )
            unknown = [column for column in key.referenced_columns if column not in target.column_names]
            _require(
                not unknown and len(key.columns) == len(key.referenced_columns),
                f"{table.qualified_name}: foreign key {key.columns} does not match {key.referenced_table}",
            )
    _check_sources_and_quarantine(tables)


def _check_sources_and_quarantine(tables: list[TableSpec]) -> None:
    files = [
        (t.source.system, t.source.file_prefix) for t in tables if t.source is not None and _is_loaded(t)
    ]
    repeated = sorted({file for file in files if files.count(file) > 1})
    _require(not repeated, f"several bronze tables load the same file: {repeated}")
    for system in sorted({system for system, _ in files}):
        quarantines = [
            t.name
            for t in tables
            if t.role == QUARANTINE_ROLE and t.source is not None and t.source.system == system
        ]
        _require(
            len(quarantines) == 1,
            f"the source system {system!r} needs exactly one quarantine table; found {quarantines}",
        )


def _is_loaded(table: TableSpec, system: str | None = None) -> bool:
    """True for a bronze table loaded from a file, optionally of one source system."""
    source = table.source
    return source is not None and source.file_prefix is not None and system in (None, source.system)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SchemaDefinitionError(message)


def _plain(value: object) -> object:
    return value.value if isinstance(value, Enum) else str(value)
