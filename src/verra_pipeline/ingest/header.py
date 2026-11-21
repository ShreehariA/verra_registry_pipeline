"""Match a file's header to the columns its bronze table declares in the schema.

Headers are matched by name, never by position, using each column's
source_header and aliases from the schema. A reordered file still loads, a
renamed header is fixed by adding an alias in JSON, and nothing here knows any
column by name.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from verra_pipeline.errors import SchemaMismatchError
from verra_pipeline.schema.model import ColumnSpec, TableSpec, normalise_header


@dataclass(frozen=True)
class HeaderMatch:
    """Which position in a record feeds each schema column, and what the file has that the schema lacks."""

    positions: Mapping[str, int]
    extra_columns: tuple[tuple[str, int], ...]
    missing_optional: tuple[str, ...]
    dropped_columns: tuple[str, ...] = ()


class HeaderMatcher:
    """Stops the run when a required column is missing or a header repeats; reports everything else."""

    def match(self, header: Sequence[str], table: TableSpec, file_name: str) -> HeaderMatch:
        owners = {key: column.name for column in table.source_columns() for key in column.accepted_headers()}
        positions: dict[str, int] = {}
        extras: list[tuple[str, int]] = []
        for position, raw in enumerate(header):
            key = normalise_header(raw) or f"unnamed_{position + 1}"
            column = owners.get(key)
            if column is None:
                extras.append((key, position))
            elif column in positions:
                raise SchemaMismatchError(
                    f"{file_name}: two headers feed the column {column}: {header[position]!r} "
                    f"and {header[positions[column]]!r}"
                )
            else:
                positions[column] = position
        _reject_missing_required(table, positions, file_name)
        named = _named_extras(extras, table, file_name)
        keep = table.unknown_columns == "keep"
        return HeaderMatch(
            positions=MappingProxyType(positions),
            extra_columns=named if keep else (),
            missing_optional=tuple(c.name for c in table.source_columns() if c.name not in positions),
            dropped_columns=() if keep else tuple(name for name, _ in named),
        )


def _reject_missing_required(table: TableSpec, positions: Mapping[str, int], file_name: str) -> None:
    missing = [
        column for column in table.source_columns() if column.required and column.name not in positions
    ]
    if missing:
        described = ", ".join(f"{column.name} (header {_headers(column)})" for column in missing)
        raise SchemaMismatchError(f"{file_name}: required columns are missing: {described}")


def _headers(column: ColumnSpec) -> str:
    return " or ".join(repr(header) for header in (column.source_header, *column.aliases))


def _named_extras(
    extras: list[tuple[str, int]], table: TableSpec, file_name: str
) -> tuple[tuple[str, int], ...]:
    """Columns the schema does not know keep their header as name, prefixed if the schema already uses it."""
    keys = [key for key, _ in extras]
    repeated = sorted({key for key in keys if keys.count(key) > 1})
    if repeated:
        raise SchemaMismatchError(f"{file_name}: these headers appear more than once: {', '.join(repeated)}")
    taken = set(table.column_names)
    return tuple((f"extra_{key}" if key in taken else key, position) for key, position in extras)
