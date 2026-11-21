"""Find the daily drops of one source system in its landing folder.

Which files make up a drop comes from the schema (each bronze table names its
file prefix); how they are named comes from the config (e.g. '{prefix}_{date}.csv').
A snapshot is only usable when every file exists for the same date: mixing
dates would compare credits retired on one day with credits issued on another.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from functools import cached_property
from pathlib import Path
from types import MappingProxyType

from verra_pipeline.errors import IncompleteSnapshotError, SnapshotNotFoundError


@dataclass(frozen=True)
class LandingFileNames:
    """The config's file-name template, used both ways: to build a name and to read one."""

    template: str

    def name(self, prefix: str, snapshot_date: date) -> str:
        return self.template.format(prefix=prefix, date=snapshot_date.isoformat())

    def pattern_for(self, prefix: str) -> str:
        """The name with the date left open, for messages, e.g. 'VerraIssuances_YYYY-MM-DD.csv'."""
        return self.template.format(prefix=prefix, date="YYYY-MM-DD")

    def parse(self, file_name: str) -> tuple[str, date] | None:
        """The prefix and date a file name encodes, or None when the name does not follow the template."""
        match = self._pattern.fullmatch(file_name)
        if match is None:
            return None
        try:
            return match["prefix"], date.fromisoformat(match["day"])
        except ValueError:
            return None

    @cached_property
    def _pattern(self) -> re.Pattern[str]:
        pattern = re.escape(self.template)
        pattern = pattern.replace(re.escape("{prefix}"), r"(?P<prefix>[A-Za-z0-9]+)")
        return re.compile(pattern.replace(re.escape("{date}"), r"(?P<day>\d{4}-\d{2}-\d{2})"))


@dataclass(frozen=True)
class Snapshot:
    """One day's drop: its date and the file feeding each bronze table."""

    snapshot_date: date
    files: Mapping[str, Path]

    def file_for(self, table: str) -> Path:
        return self.files[table]


class SnapshotFinder:
    """Looks in a landing folder for complete daily drops, ignoring every other file."""

    def __init__(
        self, landing_dir: Path, file_names: LandingFileNames, tables_by_prefix: Mapping[str, str]
    ) -> None:
        self._landing_dir = landing_dir
        self._file_names = file_names
        self._tables_by_prefix = dict(tables_by_prefix)

    def find(self, snapshot_date: date | None = None) -> Snapshot:
        """The snapshot for `snapshot_date`, or the newest complete one when no date is given."""
        drops = self._drops_by_date()
        if snapshot_date is None:
            return self._newest_complete(drops)
        return self._complete(snapshot_date, drops.get(snapshot_date, {}))

    def _drops_by_date(self) -> dict[date, dict[str, Path]]:
        if not self._landing_dir.is_dir():
            raise SnapshotNotFoundError(f"the landing folder {self._landing_dir} does not exist")
        drops: dict[date, dict[str, Path]] = {}
        for path in sorted(self._landing_dir.iterdir()):
            parsed = self._file_names.parse(path.name) if path.is_file() else None
            if parsed is not None and parsed[0] in self._tables_by_prefix:
                prefix, day = parsed
                drops.setdefault(day, {})[self._tables_by_prefix[prefix]] = path
        return drops

    def _newest_complete(self, drops: dict[date, dict[str, Path]]) -> Snapshot:
        complete_days = [day for day, files in drops.items() if len(files) == len(self._tables_by_prefix)]
        if not complete_days:
            raise SnapshotNotFoundError(self._nothing_complete(drops))
        newest = max(complete_days)
        return Snapshot(newest, MappingProxyType(drops[newest]))

    def _complete(self, snapshot_date: date, files: dict[str, Path]) -> Snapshot:
        if not files:
            raise SnapshotNotFoundError(f"no files dated {snapshot_date} in {self._landing_dir}")
        missing = [
            self._file_names.name(prefix, snapshot_date)
            for prefix, table in sorted(self._tables_by_prefix.items())
            if table not in files
        ]
        if missing:
            raise IncompleteSnapshotError(f"snapshot {snapshot_date} is missing {', '.join(missing)}")
        return Snapshot(snapshot_date, MappingProxyType(dict(files)))

    def _nothing_complete(self, drops: dict[date, dict[str, Path]]) -> str:
        expected = len(self._tables_by_prefix)
        if not drops:
            names = ", ".join(
                self._file_names.pattern_for(prefix) for prefix in sorted(self._tables_by_prefix)
            )
            return f"no expected files in {self._landing_dir}; expected {names}"
        partial = ", ".join(f"{day} has {len(files)} of {expected}" for day, files in sorted(drops.items()))
        return f"no date has all {expected} expected files in {self._landing_dir} ({partial})"
