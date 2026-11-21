"""Command line: `verra ingest`, `verra query` and `verra schema`.

This file is the composition root. It finds and loads the config, loads the
schema, builds the concrete objects, hands them to a stage and prints the
result. Nothing below it knows about arguments or the terminal, and nothing in
it knows a path, a file name or a column: those come from the config and the
schema.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from verra_pipeline.config import (
    CONFIG_ENV_VAR,
    DEFAULT_CONFIG_FILE,
    ConfigLocator,
    PipelineConfig,
    SourceSystem,
)
from verra_pipeline.errors import PipelineError, SchemaDefinitionError
from verra_pipeline.ingest.csv_reader import CsvFileReader
from verra_pipeline.ingest.header import HeaderMatcher
from verra_pipeline.ingest.loader import FileLoader
from verra_pipeline.ingest.reject_budget import RejectBudget
from verra_pipeline.ingest.report import IngestReport
from verra_pipeline.ingest.stage import IngestPlan, IngestStage
from verra_pipeline.lake import LocalLake
from verra_pipeline.schema.model import ColumnSpec, TableSpec
from verra_pipeline.schema.registry import SchemaRegistry, layer_order
from verra_pipeline.snapshot import LandingFileNames, SnapshotFinder
from verra_pipeline.text_table import format_table
from verra_pipeline.warehouse import LocalWarehouse, ViewNames


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        arguments.run(arguments)
    except PipelineError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


def _parser() -> argparse.ArgumentParser:
    locations = argparse.ArgumentParser(add_help=False)
    locations.add_argument(
        "--config",
        type=Path,
        help=f"config file (default: ${CONFIG_ENV_VAR}, else {DEFAULT_CONFIG_FILE} "
        "in this folder or the nearest folder above)",
    )
    locations.add_argument("--schema", type=Path, help="schema folder to use instead of the config's")
    locations.add_argument("--lake", type=Path, help="lake folder to use instead of the config's")
    locations.add_argument("--warehouse", type=Path, help="DuckDB file to use instead of the config's")

    parser = argparse.ArgumentParser(prog="verra", description="Verra registry pipeline.")
    commands = parser.add_subparsers(required=True, metavar="command")

    ingest = commands.add_parser(
        "ingest",
        parents=[locations],
        help="load a source system's snapshot from its landing folder into bronze",
    )
    ingest.add_argument(
        "--source", help="source system to load, as named in the config (default: the only one)"
    )
    ingest.add_argument(
        "--snapshot", type=_iso_date, help="date to load, YYYY-MM-DD (default: newest complete)"
    )
    ingest.add_argument(
        "--landing", type=Path, help="read this folder instead of the source's landing folder"
    )
    ingest.add_argument(
        "--max-rejected-share",
        type=float,
        help="stop if more than this share of a file is unreadable (default: from the config)",
    )
    ingest.set_defaults(run=_run_ingest)

    query = commands.add_parser("query", parents=[locations], help="run SQL against the loaded layers")
    query.add_argument("sql", help='e.g. "select count(*) from bronze.retirements"')
    query.set_defaults(run=_run_query)

    schema = commands.add_parser(
        "schema", parents=[locations], help="list the tables the schema declares, or one table's columns"
    )
    schema.add_argument("--layer", choices=layer_order(), help="only this layer")
    schema.add_argument("--table", help="show this table's columns")
    schema.set_defaults(run=_run_schema)
    return parser


def _config(arguments: argparse.Namespace) -> PipelineConfig:
    file = ConfigLocator(os.environ, Path.cwd()).locate(arguments.config)
    return PipelineConfig.load(file).overridden(
        schema=arguments.schema, lake=arguments.lake, warehouse=arguments.warehouse
    )


def _run_ingest(arguments: argparse.Namespace) -> None:
    config = _config(arguments).overridden(max_rejected_share=arguments.max_rejected_share)
    source = config.source(arguments.source).with_landing(arguments.landing)
    plan = IngestPlan.from_registry(SchemaRegistry.load(config.paths.schema), source.name)
    lake = LocalLake(config.paths.lake, config.lake_table_file, config.lake_manifest_file)
    stage = IngestStage(
        finder=SnapshotFinder(source.landing, LandingFileNames(source.file_name), plan.tables_by_prefix()),
        loader=FileLoader(CsvFileReader(), HeaderMatcher(), RejectBudget(config.max_rejected_share)),
        lake=lake,
        plan=plan,
    )
    report = stage.run(arguments.snapshot)
    views = ViewNames(config.current_view, config.history_view)
    layer = plan.quarantine.layer
    LocalWarehouse(config.paths.warehouse).create_views(
        layer, views.for_snapshot(lake, layer, plan.table_names(), report.snapshot_date)
    )
    print(
        _ingest_summary(report, source, config, lake.manifest_file(plan.manifest_name, report.snapshot_date))
    )


def _run_query(arguments: argparse.Namespace) -> None:
    result = LocalWarehouse(_config(arguments).paths.warehouse).query(arguments.sql)
    print(format_table(result.columns, result.rows))


def _run_schema(arguments: argparse.Namespace) -> None:
    registry = SchemaRegistry.load(_config(arguments).paths.schema)
    if arguments.table is None:
        print(_tables_listing(registry, arguments.layer))
    else:
        print(_columns_listing(_find_table(registry, arguments.layer, arguments.table)))


def _find_table(registry: SchemaRegistry, layer: str | None, name: str) -> TableSpec:
    matches = [table for table in registry.tables(layer) if table.name == name]
    if len(matches) != 1:
        where = "in any layer" if not matches else "in several layers; add --layer"
        raise SchemaDefinitionError(f"no single table called {name!r} {where}")
    return matches[0]


def _ingest_summary(
    report: IngestReport, source: SourceSystem, config: PipelineConfig, manifest: Path
) -> str:
    table = format_table(
        ("table", "file", "rows read", "loaded", "quarantined", "encoding", "line endings"),
        [
            (
                f.table,
                f.profile.file_name,
                f"{f.rows_read:,}",
                f"{f.rows_accepted:,}",
                f"{f.rows_rejected:,}",
                f.profile.encoding,
                f.profile.line_endings,
            )
            for f in report.files
        ],
        right_aligned={2, 3, 4},
    )
    findings = [f"  {file.profile.file_name}: {note}" for file in report.files for note in file.findings()]
    lines = [
        f"Source {report.system}, snapshot {report.snapshot_date}, read from {_shown(source.landing)}",
        "",
        table,
        "",
    ]
    if findings:
        lines += ["Findings", *findings, ""]
    lines += [
        f"Written to {_shown(config.paths.lake)}; quarantine table: {report.quarantine_table}",
        f"Manifest: {_shown(manifest)}",
        f"Schema fingerprint: {report.schema_fingerprint[:16]}",
        f'Look inside: uv run verra query "select count(*) from {report.layer}.{report.files[-1].table}"',
    ]
    return "\n".join(lines)


def _tables_listing(registry: SchemaRegistry, layer: str | None) -> str:
    rows = [(t.layer, t.name, len(t.columns), _loaded_from(t), t.description) for t in registry.tables(layer)]
    listing = format_table(("layer", "table", "columns", "loaded from", "description"), rows)
    return f"{listing}\n\nSchema fingerprint: {registry.fingerprint()[:16]}"


def _loaded_from(table: TableSpec) -> str:
    if table.source is None:
        return ""
    return f"{table.source.system}: {table.source.file_prefix or table.role}"


def _columns_listing(table: TableSpec) -> str:
    header = [f"{table.qualified_name}: {table.description}"]
    if table.grain:
        header.append(f"Grain: {table.grain}")
    if table.primary_key:
        header.append(f"Primary key: {', '.join(table.primary_key)}")
    rows = [
        (position, c.name, c.type.value, "yes" if c.nullable else "no", _filled_from(c), c.description)
        for position, c in enumerate(table.columns, start=1)
    ]
    listing = format_table(("#", "column", "type", "nullable", "filled from", "description"), rows)
    return "\n".join([*header, "", listing])


def _filled_from(column: ColumnSpec) -> str:
    if column.generated is not None:
        return f"generated: {column.generated}"
    if column.source_header is None:
        return "transformation"
    headers = " or ".join(repr(h) for h in (column.source_header, *column.aliases))
    return f"header {headers}" + (" (required)" if column.required else "")


def _shown(path: Path) -> str:
    """A path relative to the current folder when it is inside it, otherwise absolute."""
    try:
        return str(path.relative_to(Path.cwd()))
    except ValueError:
        return str(path)


def _iso_date(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"{text!r} is not a date like 2026-11-17") from error


if __name__ == "__main__":
    sys.exit(main())
