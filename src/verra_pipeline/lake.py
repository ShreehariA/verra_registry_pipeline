"""Where every layer is kept: one Parquet file per table and snapshot date, plus DuckDB views for SQL.

A build writes its tables and then, last, a manifest that marks the snapshot finished. Every file
is written under a temporary name and then renamed, so a crash never leaves half a file behind,
and readers only ever see finished snapshots.
"""

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


def connect(lake: Path) -> duckdb.DuckDBPyConnection:
    """An in-memory database with a view per table of the newest finished snapshot, e.g. gold.dim_project.

    A build writes its manifest last, so a snapshot without one was interrupted and stays hidden.
    The views are not saved to a file: a DuckDB file's bytes change on every write, and only one
    process can write it, so a build would fail while the dashboard has it open.
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
            f"CREATE VIEW {layer}.{table} AS "
            f"SELECT * FROM read_parquet('{location}', hive_partitioning = false)"
        )
    return con


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
