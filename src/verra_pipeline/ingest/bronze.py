"""Shape loaded files into bronze tables, exactly as the schema declares them.

The columns are the table's schema columns in schema order: values read from
the file (matched by header), and values the pipeline fills in, such as the
source file and line. Any column the file has but the schema does not know is
added at the end as text, so nothing delivered is ever dropped. Bronze changes
no value; cleaning is the silver stage's job.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from types import MappingProxyType

from verra_pipeline.ingest.csv_reader import FileProfile, ParsedRecord, RejectedRecord
from verra_pipeline.ingest.header import HeaderMatch
from verra_pipeline.ingest.loader import LoadedFile
from verra_pipeline.lake import Cell, TableData
from verra_pipeline.schema.model import ColumnSpec, ColumnType, TableSpec

EXTRA_COLUMN_DESCRIPTION = "Not in the schema; kept as delivered."


@dataclass(frozen=True)
class RowOrigin:
    """Everything a generated column can be filled from, for one row."""

    snapshot_date: date
    profile: FileProfile
    target_table: str
    line_number: int
    rejected: RejectedRecord | None = None


def _line_count(origin: RowOrigin) -> Cell:
    return None if origin.rejected is None else origin.rejected.line_count


def _reject_reason(origin: RowOrigin) -> Cell:
    return None if origin.rejected is None else origin.rejected.reason


def _raw_text(origin: RowOrigin) -> Cell:
    return None if origin.rejected is None else origin.rejected.raw_text


GENERATED_VALUES: Mapping[str, Callable[[RowOrigin], Cell]] = MappingProxyType(
    {
        "snapshot_date": lambda origin: origin.snapshot_date,
        "source_file": lambda origin: origin.profile.file_name,
        "source_line": lambda origin: origin.line_number,
        "file_sha256": lambda origin: origin.profile.sha256,
        "target_table": lambda origin: origin.target_table,
        "line_count": _line_count,
        "reject_reason": _reject_reason,
        "raw_text": _raw_text,
    }
)
"""How each `generated` key in the schema is filled; the table format lists the same keys."""

ValueGetter = Callable[[ParsedRecord, RowOrigin], Cell]


def bronze_table(loaded: LoadedFile, snapshot_date: date) -> TableData:
    """Every readable row of one file, in the shape its bronze table declares."""
    table, match, profile = loaded.table, loaded.header, loaded.parsed.profile
    extras = tuple(
        ColumnSpec(name, ColumnType.TEXT, EXTRA_COLUMN_DESCRIPTION) for name, _ in match.extra_columns
    )
    getters = [_getter(column, match) for column in table.columns]
    extra_positions = [position for _, position in match.extra_columns]
    rows = tuple(
        _row(
            record,
            RowOrigin(snapshot_date, profile, table.name, record.line_number),
            getters,
            extra_positions,
        )
        for record in loaded.parsed.records
    )
    return TableData(table.columns + extras, rows)


def _row(
    record: ParsedRecord, origin: RowOrigin, getters: Sequence[ValueGetter], extra_positions: Sequence[int]
) -> tuple[Cell, ...]:
    return (
        *(get(record, origin) for get in getters),
        *(record.values[position] for position in extra_positions),
    )


def quarantine_table(files: Sequence[LoadedFile], table: TableSpec, snapshot_date: date) -> TableData:
    """Every unreadable row of the snapshot, in the shape the quarantine table declares."""
    rows: list[tuple[Cell, ...]] = []
    for loaded in files:
        for rejected in loaded.parsed.rejected:
            origin = RowOrigin(
                snapshot_date, loaded.parsed.profile, loaded.table.name, rejected.line_number, rejected
            )
            rows.append(tuple(_generated(column, origin) for column in table.columns))
    return TableData(table.columns, tuple(rows))


def _getter(column: ColumnSpec, match: HeaderMatch) -> ValueGetter:
    """How to fill one column for each record: generate it, read it from the file, or leave it empty."""
    if column.generated is not None:
        fill = GENERATED_VALUES[column.generated]
        return lambda record, origin: fill(origin)
    position = match.positions.get(column.name)
    if position is None:
        return lambda record, origin: None
    return lambda record, origin: record.values[position]


def _generated(column: ColumnSpec, origin: RowOrigin) -> Cell:
    if column.generated is None:
        raise ValueError(f"{column.name} is not a generated column")
    return GENERATED_VALUES[column.generated](origin)
