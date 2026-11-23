"""Where every layer is kept: one Parquet file per table and snapshot date, plus DuckDB views for SQL.

A re-run replaces exactly its own snapshot's files, and every file is written under a
temporary name and then renamed, so a crash never leaves half a file behind.
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


def partition(lake: Path, layer: str, table: str, day: date) -> Path:
    return lake / layer / table / f"snapshot_date={day}" / "data.parquet"


def write_parquet(rows: duckdb.DuckDBPyRelation, path: Path) -> None:
    _replace_atomically(path, lambda temporary: rows.write_parquet(str(temporary)))


def write_json(document: dict[str, Any], path: Path) -> None:
    text = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
    _replace_atomically(path, lambda temporary: temporary.write_text(text, encoding="utf-8"))


def connect(lake: Path) -> duckdb.DuckDBPyConnection:
    """An in-memory database with a view per table on the newest finished snapshot, e.g. bronze.retirements.

    A build writes its manifest last, so a snapshot without one was interrupted and stays hidden.
    The views are not saved to a file: a DuckDB file's bytes change on every write, and only one
    process can write it, so a build would fail while the dashboard has it open.
    """
    finished = sorted(lake.glob("_manifests/snapshot_date=*/ingest.json"))
    if not finished:
        raise PipelineError(f"nothing has been built in {lake} yet; run `verra build` first")
    con = duckdb.connect()
    for path in sorted(lake.glob(f"*/*/{finished[-1].parent.name}/data.parquet")):
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


def _replace_atomically(target: Path, write: Callable[[Path], object]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp")
    try:
        write(temporary)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    temporary.replace(target)
