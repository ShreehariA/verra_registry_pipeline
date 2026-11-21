"""Turn one raw CSV file into records, without trusting it.

The reader records facts about the file itself (checksum, encoding, line
endings), parses it with the csv module so quoted commas and line breaks are
handled, and moves any record with the wrong number of fields to quarantine
instead of guessing what it meant.
"""

from __future__ import annotations

import codecs
import csv
import hashlib
import io
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from verra_pipeline.errors import UnreadableFileError

_BOMS = (codecs.BOM_UTF8, codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)


@dataclass(frozen=True)
class FileProfile:
    """Facts about a file, recorded before any of its rows are trusted."""

    file_name: str
    size_bytes: int
    sha256: str
    encoding: str
    has_bom: bool
    line_endings: str
    ends_with_newline: bool


@dataclass(frozen=True)
class ParsedRecord:
    """One row as delivered; `line_number` is the line it starts on, counting the header as line 1."""

    line_number: int
    values: tuple[str, ...]


@dataclass(frozen=True)
class RejectedRecord:
    """A row that could not be read, kept with its exact text so nothing is lost silently."""

    line_number: int
    line_count: int
    reason: str
    raw_text: str


@dataclass(frozen=True)
class ParsedCsv:
    profile: FileProfile
    header: tuple[str, ...]
    records: tuple[ParsedRecord, ...]
    rejected: tuple[RejectedRecord, ...]
    blank_lines: int
    data_lines: int

    @property
    def rows_read(self) -> int:
        return len(self.records) + len(self.rejected)

    @property
    def rejected_lines(self) -> int:
        return sum(record.line_count for record in self.rejected)


class CsvFileReader:
    """Reads one comma-separated file into a ParsedCsv."""

    def read(self, path: Path) -> ParsedCsv:
        raw = path.read_bytes()
        text, encoding = _decode(raw, path.name)
        profile = FileProfile(
            file_name=path.name,
            size_bytes=len(raw),
            sha256=hashlib.sha256(raw).hexdigest(),
            encoding=encoding,
            has_bom=raw.startswith(_BOMS),
            line_endings=_line_endings(text),
            ends_with_newline=text.endswith(("\n", "\r")),
        )
        return _Parser(profile, _physical_lines(text)).parse()


class _Parser:
    """Walks the records of one decoded file and sorts them into readable and quarantined."""

    def __init__(self, profile: FileProfile, lines: list[str]) -> None:
        self._profile = profile
        self._lines = lines
        self._reader = csv.reader(iter(lines))
        self._records: list[ParsedRecord] = []
        self._rejected: list[RejectedRecord] = []
        self._blank_lines = 0

    def parse(self) -> ParsedCsv:
        header = self._header()
        header_lines = self._reader.line_num
        for first_line, last_line, fields in self._rows(after_line=header_lines):
            self._sort(first_line, last_line, fields, expected=len(header))
        return ParsedCsv(
            self._profile,
            header,
            tuple(self._records),
            tuple(self._rejected),
            self._blank_lines,
            data_lines=len(self._lines) - header_lines,
        )

    def _header(self) -> tuple[str, ...]:
        header = self._next_fields()
        if not header:
            raise UnreadableFileError(f"{self._profile.file_name} has no header row")
        return tuple(header)

    def _rows(self, after_line: int) -> Iterator[tuple[int, int, list[str]]]:
        """Each record with the first and last physical line it spans (quoted fields can span lines)."""
        last_line = after_line
        while (fields := self._next_fields()) is not None:
            first_line, last_line = last_line + 1, self._reader.line_num
            yield first_line, last_line, fields

    def _next_fields(self) -> list[str] | None:
        try:
            return next(self._reader, None)
        except csv.Error as error:
            raise UnreadableFileError(
                f"{self._profile.file_name} is not valid CSV near line {self._reader.line_num}: {error}"
            ) from error

    def _sort(self, first_line: int, last_line: int, fields: list[str], expected: int) -> None:
        if not fields:
            self._blank_lines += 1
        elif len(fields) == expected:
            self._records.append(ParsedRecord(first_line, tuple(fields)))
        else:
            self._rejected.append(
                RejectedRecord(
                    line_number=first_line,
                    line_count=last_line - first_line + 1,
                    reason=self._reason(len(fields), expected, last_line),
                    raw_text="".join(self._lines[first_line - 1 : last_line]),
                )
            )

    def _reason(self, found: int, expected: int, last_line: int) -> str:
        reason = f"expected {expected} fields, found {found}"
        if last_line == len(self._lines) and not self._profile.ends_with_newline:
            reason += "; the file ends inside this record, so it was probably cut off"
        return reason


def _decode(raw: bytes, file_name: str) -> tuple[str, str]:
    """The text and the encoding that worked. UTF-8 is expected; Windows-1252 is the fallback."""
    if raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        try:
            return raw.decode("utf-16"), "utf-16"
        except UnicodeDecodeError as error:
            raise UnreadableFileError(
                f"{file_name} looks like UTF-16 but does not decode: {error}"
            ) from error
    try:
        return raw.decode("utf-8-sig"), "utf-8-sig" if raw.startswith(codecs.BOM_UTF8) else "utf-8"
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace"), "cp1252"


def _physical_lines(text: str) -> list[str]:
    """The file's lines with their endings kept, split exactly the way the csv module splits them."""
    return io.StringIO(text, newline="").readlines()


def _line_endings(text: str) -> str:
    """'LF', 'CRLF' or 'CR'; 'mixed' when more than one is used; 'none' for a one-line file."""
    crlf = text.count("\r\n")
    counts = {"CRLF": crlf, "LF": text.count("\n") - crlf, "CR": text.count("\r") - crlf}
    used = [style for style, count in counts.items() if count]
    if not used:
        return "none"
    return used[0] if len(used) == 1 else "mixed"
