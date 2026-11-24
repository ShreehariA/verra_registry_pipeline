"""The `verra` command: `verra build` makes every layer from the raw files; `verra query` runs SQL on them."""

from __future__ import annotations

import argparse
import dataclasses
import os
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

import duckdb

from verra_pipeline import PipelineError
from verra_pipeline.config import Config, load
from verra_pipeline.ingest import ingest
from verra_pipeline.lake import connect, newest_manifest, publish
from verra_pipeline.transform import describe, transform

LOCATIONS = ("landing", "lake")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="verra", description="Verra registry pipeline.")
    parser.add_argument("--config", type=Path, default=Path("pipeline.toml"), help="default: pipeline.toml")
    commands = parser.add_subparsers(dest="command", required=True)
    build_command = commands.add_parser("build", help="build every layer from the newest complete snapshot")
    build_command.add_argument(
        "--snapshot", type=date.fromisoformat, help="load this date instead (YYYY-MM-DD)"
    )
    for name in LOCATIONS:
        build_command.add_argument(
            f"--{name}", type=Path, help=f"use this {name} instead of the config's, for one run"
        )
    query = commands.add_parser("query", help="run SQL on the newest snapshot of every table")
    query.add_argument("sql")
    args = parser.parse_args(argv)
    try:
        config = load(args.config)
        if args.command == "build":
            config = dataclasses.replace(
                config, **{name: getattr(args, name) for name in LOCATIONS if getattr(args, name)}
            )
            print(_report(build(config, args.snapshot), config))
        else:
            _query(config.lake, args.sql)
    except (PipelineError, OSError) as error:  # OSError: a folder that can't be read or written
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


def build(config: Config, snapshot: date | None = None) -> dict[str, Any]:
    """Ingest, transform and check one snapshot in memory, then write every layer and, last, the manifest.

    Every check runs before anything is written, so a failed one leaves the lake exactly as it was.
    """
    with duckdb.connect() as con:
        con.execute("SET threads = 1")  # one thread: the same input always gives the same bytes
        manifest = ingest(con, config, snapshot)
        manifest |= transform(con, config.sql, date.fromisoformat(manifest["snapshot_date"]))
        publish(con, config.lake, manifest)
    return manifest


def _query(lake: Path, sql: str) -> None:
    try:
        with connect(lake) as con:
            result = con.sql(sql)
            if result is not None:  # statements such as SET return no rows
                result.show()
    except duckdb.Error as error:
        raise PipelineError(f"the query failed: {error}") from error


def _report(manifest: dict[str, Any], config: Config) -> str:
    lines = [f"Snapshot {manifest['snapshot_date']} from {os.path.relpath(config.landing)}", ""]
    for f in manifest["files"]:
        counts = (
            f"{f['rows_read']:>8,} read{f['rows_loaded']:>9,} loaded{f['rows_quarantined']:>4,} quarantined"
        )
        lines.append(f"  {f['table']:<14}{counts}")
    findings = [f"  {note}" for note in manifest["skipped"]]
    findings += [f"  {f['file']}: {note}" for f in manifest["files"] for note in f["findings"]]
    if findings:
        lines += ["", "Findings", *findings]
    errors = [c for c in manifest["checks"] if c["severity"] == "error"]
    warnings = [c for c in manifest["checks"] if c["severity"] == "warning" and not c["passed"]]
    lines += ["", f"Quality gate passed: all {len(errors)} error checks are clean"]
    lines += [f"  warning: {describe(c)}" for c in warnings]
    totals = " · ".join(f"{name} {value:,}" for name, value in manifest["credits"].items())
    lines += ["", f"Credits: {totals}", f"Written to {os.path.relpath(config.lake)}"]
    # readers show the newest finished snapshot, which may not be the one just built
    newest = newest_manifest(config.lake).parent.name.removeprefix("snapshot_date=")
    if newest != manifest["snapshot_date"]:
        lines.append(
            f"Note: the lake also holds {newest}, which is newer, so the dashboard and `verra query` "
            "show that one. Empty the lake first (make clean) to see only this snapshot."
        )
    lines.append('Look inside: uv run verra query "select * from gold.mart_project_balance limit 5"')
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
