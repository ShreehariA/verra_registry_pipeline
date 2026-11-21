"""Ingest stage: load one source system's snapshot into bronze, exactly as delivered.

Every file is read and checked before anything is written, so a bad file never
leaves bronze holding a mix of two snapshots. What to load, and the shape of
every table, come from the schema; where it goes comes from the config.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from verra_pipeline.ingest.bronze import bronze_table, quarantine_table
from verra_pipeline.ingest.loader import FileLoader, LoadedFile
from verra_pipeline.ingest.report import FileReport, IngestReport
from verra_pipeline.lake import Lake
from verra_pipeline.schema.model import TableSpec
from verra_pipeline.schema.registry import SchemaRegistry
from verra_pipeline.snapshot import SnapshotFinder

STAGE = "ingest"


@dataclass(frozen=True)
class IngestPlan:
    """What one ingest run loads: a source system's tables, its quarantine table, the schema version."""

    system: str
    tables: tuple[TableSpec, ...]
    quarantine: TableSpec
    schema_fingerprint: str

    @classmethod
    def from_registry(cls, registry: SchemaRegistry, system: str) -> IngestPlan:
        return cls(
            system, registry.sourced_tables(system), registry.quarantine_table(system), registry.fingerprint()
        )

    def tables_by_prefix(self) -> dict[str, str]:
        """File prefix to bronze table, for finding the files."""
        return {
            table.source.file_prefix: table.name
            for table in self.tables
            if table.source and table.source.file_prefix
        }

    def table_names(self) -> tuple[str, ...]:
        """Every bronze table this run writes, including the quarantine table."""
        return (*(table.name for table in self.tables), self.quarantine.name)

    @property
    def manifest_name(self) -> str:
        """One manifest per source system and date, so systems never overwrite each other's record."""
        return f"{STAGE}_{self.system}"


class IngestStage:
    """Finds a snapshot, loads its files, and writes them to bronze with a manifest."""

    def __init__(self, finder: SnapshotFinder, loader: FileLoader, lake: Lake, plan: IngestPlan) -> None:
        self._finder = finder
        self._loader = loader
        self._lake = lake
        self._plan = plan

    def run(self, snapshot_date: date | None = None) -> IngestReport:
        snapshot = self._finder.find(snapshot_date)
        loaded = [self._loader.load(snapshot.file_for(table.name), table) for table in self._plan.tables]
        day = snapshot.snapshot_date
        quarantine = self._plan.quarantine
        report = IngestReport(
            snapshot_date=day,
            system=self._plan.system,
            layer=quarantine.layer,
            schema_fingerprint=self._plan.schema_fingerprint,
            files=tuple(self._store(file, day) for file in loaded),
            quarantine_table=quarantine.name,
            quarantine_output=self._lake.write_table(
                quarantine.layer, quarantine.name, day, quarantine_table(loaded, quarantine, day)
            ),
        )
        self._lake.write_manifest(self._plan.manifest_name, day, report.to_manifest())
        return report

    def _store(self, loaded: LoadedFile, snapshot_date: date) -> FileReport:
        table = bronze_table(loaded, snapshot_date)
        output = self._lake.write_table(loaded.table.layer, loaded.table.name, snapshot_date, table)
        return FileReport.of(loaded, table.column_names(), output)
