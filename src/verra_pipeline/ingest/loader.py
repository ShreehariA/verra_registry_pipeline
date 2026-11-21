"""Turn one file path into a file the pipeline can trust, or stop with a clear reason."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from verra_pipeline.errors import UnreadableFileError
from verra_pipeline.ingest.csv_reader import CsvFileReader, ParsedCsv
from verra_pipeline.ingest.header import HeaderMatch, HeaderMatcher
from verra_pipeline.ingest.reject_budget import RejectBudget
from verra_pipeline.schema.model import TableSpec


@dataclass(frozen=True)
class LoadedFile:
    """A parsed file, matched to its bronze table, whose reject rate has been checked."""

    table: TableSpec
    parsed: ParsedCsv
    header: HeaderMatch


class FileLoader:
    """Reads a file, then checks it: header against the schema, at least one row, reject budget."""

    def __init__(self, reader: CsvFileReader, matcher: HeaderMatcher, budget: RejectBudget) -> None:
        self._reader = reader
        self._matcher = matcher
        self._budget = budget

    def load(self, path: Path, table: TableSpec) -> LoadedFile:
        parsed = self._reader.read(path)
        header = self._matcher.match(parsed.header, table, path.name)
        _require_rows(parsed)
        self._budget.check(parsed)
        return LoadedFile(table, parsed, header)


def _require_rows(parsed: ParsedCsv) -> None:
    """Every export holds the registry's full history, so an export with no rows is broken, not quiet."""
    if not parsed.records:
        raise UnreadableFileError(f"{parsed.profile.file_name} has a header but no readable rows")
