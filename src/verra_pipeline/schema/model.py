"""The shape of a table, as declared in the schema folder.

These are plain values: the registry builds them from the JSON files, and the
stages read them to know which columns exist, in what order, with what type,
and where each value comes from.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class ColumnType(Enum):
    TEXT = "text"
    INTEGER = "integer"
    DOUBLE = "double"
    BOOLEAN = "boolean"
    DATE = "date"


def normalise_header(header: str) -> str:
    """How a file header is compared with the schema: '\\ufeffRetirement QTY ' becomes 'retirement_qty'."""
    text = header.replace("﻿", "").strip().lower()
    return re.sub(r"[^0-9a-z]+", "_", text).strip("_")


@dataclass(frozen=True)
class ColumnSpec:
    name: str
    type: ColumnType
    description: str
    nullable: bool = True
    required: bool = False
    source_header: str | None = None
    aliases: tuple[str, ...] = ()
    generated: str | None = None

    @property
    def is_from_source(self) -> bool:
        """True when the value is read from a landing file rather than filled in by the pipeline."""
        return self.source_header is not None

    def accepted_headers(self) -> tuple[str, ...]:
        """The headers that may feed this column, normalised for comparison."""
        if self.source_header is None:
            return ()
        return tuple(normalise_header(header) for header in (self.source_header, *self.aliases))


@dataclass(frozen=True)
class SourceSpec:
    """The source system a bronze table belongs to (named in the config) and the prefix of its file.

    A quarantine table names only its system: it is filled with that system's unreadable records,
    not loaded from a file.
    """

    system: str
    file_prefix: str | None = None


@dataclass(frozen=True)
class ForeignKey:
    columns: tuple[str, ...]
    referenced_table: str
    referenced_columns: tuple[str, ...]


@dataclass(frozen=True)
class TableSpec:
    layer: str
    name: str
    description: str
    columns: tuple[ColumnSpec, ...]
    grain: str | None = None
    source: SourceSpec | None = None
    role: str | None = None
    unknown_columns: str = "keep"
    primary_key: tuple[str, ...] = ()
    foreign_keys: tuple[ForeignKey, ...] = ()

    @property
    def qualified_name(self) -> str:
        return f"{self.layer}.{self.name}"

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(column.name for column in self.columns)

    def source_columns(self) -> tuple[ColumnSpec, ...]:
        return tuple(column for column in self.columns if column.is_from_source)

    def column(self, name: str) -> ColumnSpec:
        for column in self.columns:
            if column.name == name:
                return column
        raise KeyError(f"{self.qualified_name} has no column {name!r}")
