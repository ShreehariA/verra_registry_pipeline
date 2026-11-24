"""Transform: build silver and gold from bronze with the SQL in sql/, then run the quality gate.

It works inside the build's in-memory database, after ingest and before anything is written. It runs
macros.sql, then each file in silver/ and gold/ in name order (one SELECT per file, which becomes the
table of the same name), then checks.sql. If an error check fails, the build stops and the lake stays
exactly as it was.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa

from verra_pipeline import PipelineError


def transform(con: duckdb.DuckDBPyConnection, sql: Path, day: date) -> dict[str, Any]:
    """Create the silver and gold tables in `con`; return the checks and the credit totals."""
    con.execute(f"SET VARIABLE snapshot_date = DATE '{day}'")
    con.register("owner_repairs", _owner_repairs(con))
    _run(con, sql / "macros.sql")
    con.execute("CREATE SCHEMA silver; CREATE SCHEMA gold")
    for path in [*sorted((sql / "silver").glob("*.sql")), *sorted((sql / "gold").glob("*.sql"))]:
        _run(con, path, f"CREATE TABLE {path.parent.name}.{path.stem} AS ")
    _run(con, sql / "checks.sql", "CREATE TABLE gold.quality_results AS ")

    checks = _records(con.table("gold.quality_results"))
    failed = [check for check in checks if check["severity"] == "error" and not check["passed"]]
    if failed:
        raise PipelineError(
            "the quality gate failed, so nothing was written: " + "; ".join(describe(c) for c in failed)
        )
    [credits] = _records(
        con.sql(
            "SELECT sum(issued) AS issued, sum(retired) AS retired, sum(cancelled) AS cancelled, "
            "sum(available) AS available FROM gold.mart_project_balance"
        )
    )
    return {"checks": checks, "credits": {name: int(value or 0) for name, value in credits.items()}}


def describe(check: dict[str, Any]) -> str:
    """A check's result in words, e.g. 'events with no readable date: 19 row(s), 209,992 credits'."""
    counts = [f"{check['failing_rows']:,} row(s)"] if check["failing_rows"] else []
    counts += [f"{check['failing_credits']:,} credits"] if check["failing_credits"] else []
    return f"{check['check_name']}: {', '.join(counts)}"


def repair(text: str) -> str:
    """Undo UTF-8 that was read as Windows-1252 before Verra exported it: 'StÃ¤dtische' is 'Städtische'.

    Text that was never mis-encoded fails the round trip ('SÃO PAULO' is real Portuguese) and stays as it is.
    """
    try:
        return text.encode("cp1252").decode("utf-8")
    except UnicodeError:
        return text


def _owner_repairs(con: duckdb.DuckDBPyConnection) -> pa.Table:
    """The owner names that need a repair, for silver to join: DuckDB itself can't re-encode text."""
    names = [
        name for (name,) in con.sql("SELECT DISTINCT beneficial_owner FROM bronze.retirements").fetchall()
    ]
    repaired = {name: fixed for name in names if name and (fixed := repair(name)) != name}
    return pa.table(
        {
            "original": pa.array(list(repaired), pa.string()),
            "repaired": pa.array(list(repaired.values()), pa.string()),
        }
    )


def _run(con: duckdb.DuckDBPyConnection, path: Path, prefix: str = "") -> None:
    """Run one SQL file; a failure names the file, in one line (the SQL and pipeline.toml must agree)."""
    try:
        con.execute(prefix + path.read_text(encoding="utf-8"))
    except duckdb.Error as error:
        raise PipelineError(f"{path} failed: {error}".replace("\n", " ")) from error


def _records(rows: duckdb.DuckDBPyRelation) -> list[dict[str, Any]]:
    return [dict(zip(rows.columns, row, strict=True)) for row in rows.fetchall()]
