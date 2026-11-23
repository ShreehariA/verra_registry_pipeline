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
from verra_pipeline.lake import connect

LOCATIONS = ("landing", "lake")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="verra", description="Verra registry pipeline.")
    parser.add_argument("--config", type=Path, default=Path("pipeline.toml"), help="default: pipeline.toml")
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="build every layer from the newest complete snapshot")
    build.add_argument("--snapshot", type=date.fromisoformat, help="load this date instead (YYYY-MM-DD)")
    for name in LOCATIONS:
        build.add_argument(
            f"--{name}", type=Path, help=f"use this {name} instead of the config's, for one run"
        )
    query = commands.add_parser("query", help="run SQL on the newest snapshot of every table")
    query.add_argument("sql")
    args = parser.parse_args(argv)
    try:
        config = load(args.config)
        if args.command == "build":
            _build(config, args)
        else:
            _query(config.lake, args.sql)
    except (PipelineError, OSError) as error:  # OSError: a folder that can't be read or written
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


def _build(config: Config, args: argparse.Namespace) -> None:
    config = dataclasses.replace(
        config, **{name: getattr(args, name) for name in LOCATIONS if getattr(args, name)}
    )
    manifest = ingest(config, args.snapshot)
    print(_report(manifest, config))


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
    findings = [f"  {f['file']}: {note}" for f in manifest["files"] for note in f["findings"]]
    if findings:
        lines += ["", "Findings", *findings]
    lines += [
        "",
        f"Written to {os.path.relpath(config.lake)}",
        'Look inside: uv run verra query "select count(*) from bronze.retirements"',
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
