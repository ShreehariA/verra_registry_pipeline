import json
import re
from datetime import date
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from verra_pipeline.errors import SchemaMismatchError
from verra_pipeline.lake import LocalLake, TableData
from verra_pipeline.schema import ColumnSpec, ColumnType

DAY = date(2030, 1, 15)
TABLE_FILE = "{layer}/{table}/snapshot_date={date}/data.parquet"
MANIFEST_FILE = "_manifests/snapshot_date={date}/{stage}.json"
COLUMNS = (
    ColumnSpec("serial_number", ColumnType.TEXT, "Serial range."),
    ColumnSpec("_source_line", ColumnType.INTEGER, "Line.", nullable=False),
    ColumnSpec("_snapshot_date", ColumnType.DATE, "Snapshot.", nullable=False),
)


def lake(root: Path, table_file: str = TABLE_FILE) -> LocalLake:
    return LocalLake(root, table_file, MANIFEST_FILE)


def table(*rows: tuple[str | None, int | None, date | None]) -> TableData:
    return TableData(COLUMNS, tuple(rows))


def test_writes_one_partition_per_snapshot_date(tmp_path: Path) -> None:
    written = lake(tmp_path).write_table("bronze", "retirements", DAY, table(("A-1", 2, DAY)))

    assert written == "bronze/retirements/snapshot_date=2030-01-15/data.parquet"
    stored = pq.read_table(tmp_path / written)
    assert stored.to_pylist() == [{"serial_number": "A-1", "_source_line": 2, "_snapshot_date": DAY}]


def test_follows_whatever_layout_the_config_gives(tmp_path: Path) -> None:
    written = lake(tmp_path, "{layer}/{date}/{table}.parquet").write_table(
        "bronze", "issuances", DAY, table()
    )

    assert written == "bronze/2030-01-15/issuances.parquet"


def test_rewriting_a_snapshot_replaces_it_and_leaves_other_dates_alone(tmp_path: Path) -> None:
    store, other_day = lake(tmp_path), date(2030, 1, 14)
    store.write_table("bronze", "retirements", other_day, table(("OLD", 2, other_day)))
    store.write_table("bronze", "retirements", DAY, table(("A-1", 2, DAY), ("A-2", 3, DAY)))

    store.write_table("bronze", "retirements", DAY, table(("A-3", 2, DAY)))

    assert pq.read_table(store.table_file("bronze", "retirements", DAY)).num_rows == 1
    assert pq.read_table(store.table_file("bronze", "retirements", other_day)).num_rows == 1


def test_leaves_no_temporary_files_behind(tmp_path: Path) -> None:
    lake(tmp_path).write_table("bronze", "retirements", DAY, table(("A-1", 2, DAY)))

    assert [p.name for p in tmp_path.rglob("*") if p.is_file()] == ["data.parquet"]


def test_an_empty_table_keeps_its_columns_and_types(tmp_path: Path) -> None:
    store = lake(tmp_path)

    store.write_table("bronze", "rejected_records", DAY, table())

    stored = pq.read_table(store.table_file("bronze", "rejected_records", DAY))
    assert stored.num_rows == 0
    assert [str(field.type) for field in stored.schema] == ["string", "int64", "date32[day]"]


def test_a_missing_value_in_a_non_nullable_column_is_refused_and_nothing_is_written(tmp_path: Path) -> None:
    store = lake(tmp_path)

    with pytest.raises(SchemaMismatchError, match=re.escape("bronze.retirements")):
        store.write_table("bronze", "retirements", DAY, table(("A-1", None, DAY)))

    assert not any(path.is_file() for path in tmp_path.rglob("*"))


def test_writes_manifests_as_json(tmp_path: Path) -> None:
    written = lake(tmp_path).write_manifest("ingest_verra", DAY, {"stage": "ingest", "rows": 3})

    assert written == "_manifests/snapshot_date=2030-01-15/ingest_verra.json"
    assert json.loads((tmp_path / written).read_text()) == {"stage": "ingest", "rows": 3}


def test_the_history_pattern_matches_every_snapshot(tmp_path: Path) -> None:
    assert lake(tmp_path).history_pattern("bronze", "issuances") == (
        tmp_path / "bronze/issuances/snapshot_date=*/data.parquet"
    )
