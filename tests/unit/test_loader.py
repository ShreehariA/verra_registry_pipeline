from pathlib import Path

import pytest

from tests.verra_files import CANCELLATION_HEADER, CANCELLATION_ROWS, write_csv
from verra_pipeline.errors import SchemaMismatchError, UnreadableFileError
from verra_pipeline.ingest.csv_reader import CsvFileReader
from verra_pipeline.ingest.header import HeaderMatcher
from verra_pipeline.ingest.loader import FileLoader
from verra_pipeline.ingest.reject_budget import RejectBudget
from verra_pipeline.schema import SchemaRegistry, TableSpec

FILE = "VerraCancelled_2030-01-15.csv"


@pytest.fixture
def cancellations(registry: SchemaRegistry) -> TableSpec:
    return registry.table("bronze", "cancellations")


def loader() -> FileLoader:
    return FileLoader(CsvFileReader(), HeaderMatcher(), RejectBudget())


def test_loads_a_good_file(tmp_path: Path, cancellations: TableSpec) -> None:
    path = write_csv(tmp_path / FILE, CANCELLATION_HEADER, CANCELLATION_ROWS)

    loaded = loader().load(path, cancellations)

    assert loaded.table is cancellations
    assert len(loaded.parsed.records) == 1
    assert loaded.header.positions["cancellation_date"] == 1


def test_a_file_with_only_a_header_is_unreadable(tmp_path: Path, cancellations: TableSpec) -> None:
    path = write_csv(tmp_path / FILE, CANCELLATION_HEADER, [])

    with pytest.raises(UnreadableFileError, match="no readable rows"):
        loader().load(path, cancellations)


def test_a_file_missing_a_required_column_stops_the_run(tmp_path: Path, cancellations: TableSpec) -> None:
    header = tuple(name for name in CANCELLATION_HEADER if name != "Serial Number")
    rows = [row[:9] + row[10:] for row in CANCELLATION_ROWS]
    path = write_csv(tmp_path / FILE, header, rows)

    with pytest.raises(SchemaMismatchError, match="serial_number"):
        loader().load(path, cancellations)
