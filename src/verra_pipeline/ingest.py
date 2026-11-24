"""Ingest: load one snapshot's raw files into the bronze layer, exactly as delivered.

Every file is read and checked first, and bronze is only loaded into the build's in-memory
database: nothing is written until the whole build has passed its checks (see cli.build).
Bronze changes no value: cleaning is silver's job.
"""

from __future__ import annotations

import codecs
import csv
import hashlib
import io
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, NamedTuple

import duckdb
import pyarrow as pa

from verra_pipeline import PipelineError
from verra_pipeline.config import Config, Source

CUT_OFF = "; the file ends inside this record, so it was probably cut off"


class Rejected(NamedTuple):
    """A record that could not be read, kept with its exact text so nothing is lost silently."""

    line: int
    line_count: int
    reason: str
    raw_text: str


@dataclass
class File:
    """One raw file, read and checked."""

    source: Source
    path: Path
    sha256: str
    columns: list[str]
    added: list[str]  # optional columns the file lacks, loaded empty
    records: list[tuple[int, list[str]]] = field(default_factory=list)  # (line it starts on, values)
    rejected: list[Rejected] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)


def ingest(con: duckdb.DuckDBPyConnection, config: Config, wanted: date | None = None) -> dict[str, Any]:
    """Load the snapshot into bronze tables in `con`; return its manifest: what was read, kept, set aside."""
    day, paths = find_snapshot(config, wanted)
    files = [read(paths[source.table], source, config.max_rejected_share) for source in config.sources]
    con.execute("CREATE SCHEMA bronze")
    for file in files:
        con.from_arrow(_bronze(file, day)).create(f"bronze.{file.source.table}")
    con.from_arrow(_quarantine(files, day)).create("bronze.rejected_records")
    return {"snapshot_date": day.isoformat(), "files": [_manifest_entry(file) for file in files]}


def find_snapshot(config: Config, wanted: date | None = None) -> tuple[date, dict[str, Path]]:
    """The requested snapshot, or the newest date with a file for every source. Other files are ignored."""
    if not config.landing.is_dir():
        raise PipelineError(f"the landing folder {config.landing} does not exist")
    pattern = (
        re.escape(config.file_name)
        .replace(re.escape("{prefix}"), "(?P<prefix>[A-Za-z0-9]+)")
        .replace(re.escape("{date}"), r"(?P<day>\d{4}-\d{2}-\d{2})")
    )
    tables = {source.prefix: source.table for source in config.sources}
    drops: dict[date, dict[str, Path]] = {}
    for path in sorted(config.landing.iterdir()):
        match = re.fullmatch(pattern, path.name)
        if match and match["prefix"] in tables and path.is_file():
            try:
                day = date.fromisoformat(match["day"])
            except ValueError:  # an impossible date such as 2026-13-45 is not a drop
                continue
            drops.setdefault(day, {})[tables[match["prefix"]]] = path
    if wanted is None:
        complete = [day for day, files in drops.items() if len(files) == len(tables)]
        if not complete:
            found = "; ".join(
                f"{day} has {len(files)} of {len(tables)}" for day, files in sorted(drops.items())
            )
            expected = ", ".join(
                config.file_name.format(prefix=prefix, date="YYYY-MM-DD") for prefix in tables
            )
            raise PipelineError(
                f"no date has all {len(tables)} files in {config.landing} ({found or 'expected ' + expected})"
            )
        wanted = max(complete)
    if wanted not in drops:
        raise PipelineError(f"no files dated {wanted} in {config.landing}")
    missing = [
        config.file_name.format(prefix=prefix, date=wanted)
        for prefix, table in tables.items()
        if table not in drops[wanted]
    ]
    if missing:
        raise PipelineError(f"snapshot {wanted} is missing {', '.join(missing)}")
    return wanted, drops[wanted]


def read(path: Path, source: Source, max_rejected_share: float) -> File:
    """Read one raw file without trusting it, and refuse it when too much of it can't be read."""
    # shortcut: the whole file is held in memory, about 15x its size; stream it once files pass ~100 MB
    raw = path.read_bytes()
    try:
        text, encoding = raw.decode("utf-8-sig"), "utf-8"
    except UnicodeDecodeError:
        text, encoding = raw.decode("cp1252", errors="replace"), "cp1252"
    lines = io.StringIO(text, newline="").readlines()  # endings kept, so quarantined text is exact
    reader = csv.reader(lines)

    def next_fields() -> list[str] | None:
        try:
            return next(reader, None)
        except csv.Error as error:
            raise PipelineError(
                f"{path.name} is not valid CSV near line {reader.line_num}: {error}"
            ) from error

    header = next_fields()
    if not header:
        raise PipelineError(f"{path.name} has no header row")
    columns = _columns(header, source, path.name)
    added = [column for column in source.optional if column not in columns]
    file = File(source, path, hashlib.sha256(raw).hexdigest(), columns, added)
    header_lines = last = reader.line_num
    blank = 0
    while (fields := next_fields()) is not None:
        first, last = last + 1, reader.line_num  # a quoted field can span several lines
        if not fields:
            blank += 1
        elif len(fields) == len(header):
            file.records.append((first, fields))
        else:
            ends_inside = last == len(lines) and not text.endswith(("\n", "\r"))
            reason = f"expected {len(header)} fields, found {len(fields)}" + (CUT_OFF if ends_inside else "")
            file.rejected.append(Rejected(first, last - first + 1, reason, "".join(lines[first - 1 : last])))
    notes = [
        (raw.startswith(codecs.BOM_UTF8), "starts with a byte-order mark, which was removed"),
        (encoding == "cp1252", "is not valid UTF-8 and was read as Windows-1252; check accented names"),
        ("\r\n" in text, "uses Windows (CRLF) line endings"),
        (not text.endswith(("\n", "\r")), "does not end with a newline, so its last record may be cut off"),
        (blank > 0, f"has {blank} blank line(s), skipped"),
        (bool(added), f"lacks optional columns, loaded empty: {', '.join(added)}"),
    ]
    file.findings = [note for applies, note in notes if applies]
    file.findings += [f"line {record.line} quarantined: {record.reason}" for record in file.rejected]
    if not file.records:
        raise PipelineError(f"{path.name} has a header but no readable rows")
    data_lines = len(lines) - header_lines
    rejected_lines = sum(record.line_count for record in file.rejected)
    if rejected_lines > max_rejected_share * data_lines:  # in lines: one broken quote can swallow thousands
        share = f"{rejected_lines / data_lines * 100:.3g}%"
        raise PipelineError(
            f"{path.name}: {rejected_lines:,} of {data_lines:,} lines ({share}) could not be read; "
            f"at most {max_rejected_share * 100:.3g}% is allowed"
        )
    return file


def _columns(header: list[str], source: Source, file_name: str) -> list[str]:
    """The file's headers, compared the way the config writes them: 'Retirement QTY' is retirement_qty."""
    names = [_normalise(name) or f"unnamed_{number}" for number, name in enumerate(header, 1)]
    columns = [source.aliases.get(name, name) for name in names]
    repeated = sorted({column for column in columns if columns.count(column) > 1})
    if repeated:
        raise PipelineError(f"{file_name}: these headers appear more than once: {', '.join(repeated)}")
    missing = [column for column in source.required if column not in columns]
    if missing:
        raise PipelineError(
            f"{file_name}: required columns are missing: {', '.join(missing)} (it has {', '.join(columns)})"
        )
    return columns


def _normalise(header: str) -> str:
    return re.sub(r"[^0-9a-z]+", "_", header.strip().lower()).strip("_")


def _bronze(file: File, day: date) -> pa.Table:
    """Every readable record as text, in file order, followed by where it came from."""
    values: dict[str, list[str | None]] = {
        name: [row[i] for _, row in file.records] for i, name in enumerate(file.columns)
    }
    values |= {name: [None] * len(file.records) for name in file.added}
    lines = [line for line, _ in file.records]
    count = len(lines)
    return pa.table(
        {name: pa.array(column, pa.string()) for name, column in values.items()}
        | _lineage(day, [file.path.name] * count, lines, [file.sha256] * count)
    )


def _quarantine(files: list[File], day: date) -> pa.Table:
    """Every unreadable record of the snapshot, with the table it was meant for, its reason and exact text."""
    rejects = [(file, record) for file in files for record in file.rejected]
    return pa.table(
        {
            "target_table": pa.array([file.source.table for file, _ in rejects], pa.string()),
            "line_count": pa.array([record.line_count for _, record in rejects], pa.int64()),
            "reason": pa.array([record.reason for _, record in rejects], pa.string()),
            "raw_text": pa.array([record.raw_text for _, record in rejects], pa.string()),
        }
        | _lineage(
            day,
            [file.path.name for file, _ in rejects],
            [record.line for _, record in rejects],
            [file.sha256 for file, _ in rejects],
        )
    )


def _lineage(day: date, files: list[str], lines: list[int], checksums: list[str]) -> dict[str, Any]:
    return {
        "_snapshot_date": pa.array([day] * len(lines), pa.date32()),
        "_source_file": pa.array(files, pa.string()),
        "_source_line": pa.array(lines, pa.int64()),
        "_file_sha256": pa.array(checksums, pa.string()),
    }


def _manifest_entry(file: File) -> dict[str, Any]:
    return {
        "table": file.source.table,
        "file": file.path.name,
        "sha256": file.sha256,
        "columns": file.columns,
        "rows_read": len(file.records) + len(file.rejected),
        "rows_loaded": len(file.records),
        "rows_quarantined": len(file.rejected),
        "findings": file.findings,
    }
