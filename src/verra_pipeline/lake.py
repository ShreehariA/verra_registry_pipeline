"""The lake: one Parquet file per table and day, and a manifest, written last, that marks the day finished."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import duckdb

from verra_pipeline import PipelineError

LAYERS = ("bronze", "silver", "gold")


def partition(lake: Path, layer: str, table: str, day: date) -> Path:
    return lake / layer / table / f"snapshot_date={day}" / "data.parquet"


def manifest_path(lake: Path, day: date) -> Path:
    return lake / "_manifests" / f"snapshot_date={day}" / "build.json"


def publish(con: duckdb.DuckDBPyConnection, lake: Path, manifest: dict[str, Any]) -> None:
    """Write every bronze, silver and gold table in `con` for the manifest's day, then the manifest itself."""
    day = date.fromisoformat(manifest["snapshot_date"])
    manifest_path(lake, day).unlink(missing_ok=True)  # rebuilding a day: hidden until it's whole again
    tables = con.sql(
        f"SELECT schema_name, table_name FROM duckdb_tables() WHERE schema_name IN {LAYERS} ORDER BY ALL"
    ).fetchall()
    for layer, table in tables:
        write_parquet(con.table(f"{layer}.{table}"), partition(lake, layer, table, day))
    write_json(manifest, manifest_path(lake, day))


def write_parquet(rows: duckdb.DuckDBPyRelation, path: Path) -> None:
    _replace_atomically(path, lambda temporary: rows.write_parquet(str(temporary)))


def write_json(document: dict[str, Any], path: Path) -> None:
    text = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
    _replace_atomically(path, lambda temporary: temporary.write_text(text, encoding="utf-8"))


def connect(lake: Path, copy: bool = False) -> duckdb.DuckDBPyConnection:
    """An in-memory database with a view per table of the newest finished snapshot, e.g. gold.dim_project.

    Not a saved DuckDB file: its bytes change on every write, and a build couldn't write it while the
    dashboard has it open. With `copy`, the tables are loaded into memory, so no file is read afterwards.
    """
    snapshot = newest_manifest(lake).parent.name
    con = duckdb.connect()
    for path in sorted(lake.glob(f"*/*/{snapshot}/data.parquet")):
        layer, table = path.parts[-4:-2]
        if not all(re.fullmatch(r"[a-z_][a-z0-9_]*", name) for name in (layer, table)):
            raise PipelineError(f"unexpected folder in the lake, not a table: {path.parent.parent}")
        location = str(path.resolve()).replace("'", "''")
        con.execute(f"CREATE SCHEMA IF NOT EXISTS {layer}")
        con.execute(
            f"CREATE {'TABLE' if copy else 'VIEW'} {layer}.{table} AS "
            f"SELECT * FROM read_parquet('{location}', hive_partitioning = false)"
        )
    return con


def lock_down(con: duckdb.DuckDBPyConnection, seconds: int) -> None:
    """Make a `connect(lake, copy=True)` connection safe for SQL typed by anyone.

    It has no file or network access, only its own copy of the tables. Allowing just the lake's folder
    isn't enough: DuckDB would let a query write there, over the files the dashboard reads.
    shortcut: every query copies the whole snapshot (50 ms and 44 MB today); past a few hundred MB,
    open a read-only DuckDB file of the snapshot instead.
    """
    con.execute(f"""
        SET temp_directory = '';  -- nowhere to spill: too big for memory fails, never writes to disk
        SET enable_external_access = false;  -- after this, DuckDB won't change temp_directory
        SET threads = 1;
        SET memory_limit = '256MB';
        SET max_execution_time = {seconds * 1000};  -- milliseconds
        SET lock_configuration = true;
    """)


def newest_manifest(lake: Path) -> Path:
    """The manifest of the newest finished snapshot: the build writes it last."""
    finished = sorted(lake.glob("_manifests/snapshot_date=*/build.json"))
    if not finished:
        raise PipelineError(f"nothing has been built in {lake} yet; run `verra build` first")
    return finished[-1]


def _replace_atomically(target: Path, write: Callable[[Path], object]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp")
    try:
        write(temporary)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    temporary.replace(target)
