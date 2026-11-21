"""What an ingest run found and did: plain sentences for people, a manifest for machines.

The manifest has no timestamps, so ingesting the same files twice produces the
same manifest; when a run happened belongs in the run log, not in the data. It
records the schema fingerprint, so every partition can be traced to the exact
table definitions that produced it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from verra_pipeline.ingest.csv_reader import FileProfile, RejectedRecord
from verra_pipeline.ingest.loader import LoadedFile


@dataclass(frozen=True)
class FileReport:
    table: str
    profile: FileProfile
    columns: tuple[str, ...]
    extra_columns: tuple[str, ...]
    dropped_columns: tuple[str, ...]
    missing_optional: tuple[str, ...]
    rows_read: int
    rows_accepted: int
    rejected: tuple[RejectedRecord, ...]
    blank_lines: int
    output: str

    @classmethod
    def of(cls, loaded: LoadedFile, columns: tuple[str, ...], output: str) -> FileReport:
        parsed = loaded.parsed
        return cls(
            table=loaded.table.name,
            profile=parsed.profile,
            columns=columns,
            extra_columns=tuple(name for name, _ in loaded.header.extra_columns),
            dropped_columns=loaded.header.dropped_columns,
            missing_optional=loaded.header.missing_optional,
            rows_read=parsed.rows_read,
            rows_accepted=len(parsed.records),
            rejected=parsed.rejected,
            blank_lines=parsed.blank_lines,
            output=output,
        )

    @property
    def rows_rejected(self) -> int:
        return len(self.rejected)

    def findings(self) -> tuple[str, ...]:
        """One sentence for each unusual thing about the file, always in the same order."""
        profile = self.profile
        notes = []
        if profile.has_bom:
            notes.append("starts with a byte-order mark, which was removed")
        if profile.encoding == "cp1252":
            notes.append("is not valid UTF-8 and was read as Windows-1252; check accented names")
        if profile.line_endings not in ("LF", "none"):
            notes.append(f"uses {profile.line_endings} line endings")
        if not profile.ends_with_newline:
            notes.append("does not end with a newline, so its last record may be cut off")
        if self.blank_lines:
            notes.append(f"has {self.blank_lines} blank line(s), skipped")
        notes.extend(
            f"line {rejected.line_number} quarantined: {rejected.reason}" for rejected in self.rejected
        )
        if self.missing_optional:
            notes.append(f"lacks optional columns, left empty: {', '.join(self.missing_optional)}")
        if self.extra_columns:
            notes.append(
                f"has columns the schema does not know, kept as text: {', '.join(self.extra_columns)}"
            )
        if self.dropped_columns:
            notes.append(
                f"has columns the schema does not declare, left out: {', '.join(self.dropped_columns)}"
            )
        return tuple(notes)

    def to_manifest(self) -> dict[str, object]:
        profile = self.profile
        return {
            "table": self.table,
            "file": profile.file_name,
            "sha256": profile.sha256,
            "size_bytes": profile.size_bytes,
            "encoding": profile.encoding,
            "has_bom": profile.has_bom,
            "line_endings": profile.line_endings,
            "ends_with_newline": profile.ends_with_newline,
            "rows_read": self.rows_read,
            "rows_loaded": self.rows_accepted,
            "rows_quarantined": self.rows_rejected,
            "blank_lines": self.blank_lines,
            "columns": list(self.columns),
            "extra_columns": list(self.extra_columns),
            "dropped_columns": list(self.dropped_columns),
            "missing_optional_columns": list(self.missing_optional),
            "quarantined": [{"line": r.line_number, "reason": r.reason} for r in self.rejected],
            "findings": list(self.findings()),
            "output": self.output,
        }


@dataclass(frozen=True)
class IngestReport:
    snapshot_date: date
    system: str
    layer: str
    schema_fingerprint: str
    files: tuple[FileReport, ...]
    quarantine_table: str
    quarantine_output: str

    @property
    def rows_rejected(self) -> int:
        return sum(file.rows_rejected for file in self.files)

    def to_manifest(self) -> dict[str, object]:
        return {
            "stage": "ingest",
            "source_system": self.system,
            "snapshot_date": self.snapshot_date.isoformat(),
            "schema_fingerprint": self.schema_fingerprint,
            "files": [file.to_manifest() for file in self.files],
            "quarantine": {
                "table": self.quarantine_table,
                "rows": self.rows_rejected,
                "output": self.quarantine_output,
            },
        }
