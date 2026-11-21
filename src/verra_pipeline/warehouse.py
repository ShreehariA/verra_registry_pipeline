"""A DuckDB file holding views over the lake, so every layer can be queried with SQL.

The views store no data; they read the Parquet files each time they are
queried, so rebuilding the lake never leaves stale copies in here. They read
with union_by_name, so a column added to the schema later shows up as NULL in
older snapshots instead of breaking the history view.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import duckdb

from verra_pipeline.errors import PipelineError
from verra_pipeline.lake import LocalLake

_SAFE_NAME = re.compile(r"^[a-z_][a-z0-9_]*$")


@dataclass(frozen=True)
class ViewNames:
    """The config's view-name templates, e.g. '{table}' for the latest snapshot and '{table}_history'."""

    current: str
    history: str

    def for_snapshot(
        self, lake: LocalLake, layer: str, tables: Iterable[str], snapshot_date: date
    ) -> dict[str, Path]:
        """View name to the files it reads: one snapshot for the current view, all of them for history."""
        views: dict[str, Path] = {}
        for table in tables:
            views[self.current.format(table=table)] = lake.table_file(layer, table, snapshot_date)
            views[self.history.format(table=table)] = lake.history_pattern(layer, table)
        return views


@dataclass(frozen=True)
class QueryResult:
    columns: tuple[str, ...]
    rows: tuple[tuple[object, ...], ...]


class LocalWarehouse:
    """One DuckDB file on this machine: views over the lake, and read-only SQL against them."""

    def __init__(self, database_file: Path) -> None:
        self._database_file = database_file

    def create_views(self, schema: str, views: Mapping[str, Path]) -> None:
        """Create or replace `<schema>.<view>` for each view, reading the Parquet files it maps to."""
        self._database_file.parent.mkdir(parents=True, exist_ok=True)
        with duckdb.connect(str(self._database_file)) as connection:
            connection.execute(f"CREATE SCHEMA IF NOT EXISTS {_safe(schema)}")
            for view, files in views.items():
                connection.execute(
                    f"CREATE OR REPLACE VIEW {_safe(schema)}.{_safe(view)} AS "
                    f"SELECT * FROM read_parquet({_quoted(files)}, union_by_name = true)"
                )

    def query(self, sql: str) -> QueryResult:
        if not self._database_file.exists():
            raise PipelineError("nothing has been loaded yet; run `verra ingest` first")
        try:
            with duckdb.connect(str(self._database_file), read_only=True) as connection:
                cursor = connection.execute(sql)
                columns = tuple(description[0] for description in cursor.description or ())
                return QueryResult(columns, tuple(cursor.fetchall()))
        except duckdb.Error as error:
            raise PipelineError(f"the query failed: {error}") from error


def _safe(name: str) -> str:
    """Schema and view names come from the schema and config files; check them before they go into SQL."""
    if not _SAFE_NAME.match(name):
        raise PipelineError(f"{name!r} is not a usable SQL name; use lower-case letters, digits and _")
    return name


def _quoted(path: Path) -> str:
    """An absolute path as a SQL string, so the views work from any working directory."""
    return "'" + str(path.resolve()).replace("'", "''") + "'"
