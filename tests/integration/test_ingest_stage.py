import hashlib
import json
import re
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import pytest

from tests.verra_files import (
    FIXTURE_DAY,
    ISSUANCE_HEADER,
    ISSUANCE_ROWS,
    RETIREMENT_HEADER,
    RETIREMENT_ROWS,
    copy_schema,
    edit_json,
    file_name,
    write_csv,
)
from verra_pipeline.errors import RejectBudgetExceededError, SchemaMismatchError
from verra_pipeline.ingest.csv_reader import CsvFileReader
from verra_pipeline.ingest.header import HeaderMatcher
from verra_pipeline.ingest.loader import FileLoader
from verra_pipeline.ingest.reject_budget import RejectBudget
from verra_pipeline.ingest.report import IngestReport
from verra_pipeline.ingest.stage import IngestPlan, IngestStage
from verra_pipeline.lake import LocalLake
from verra_pipeline.schema import SchemaRegistry
from verra_pipeline.snapshot import LandingFileNames, SnapshotFinder

TABLE_FILE = "{layer}/{table}/snapshot_date={date}/data.parquet"
MANIFEST_FILE = "_manifests/snapshot_date={date}/{stage}.json"
# The fixture's retirements file is 4 lines long and its last line is cut off,
# so a quarter of it is unreadable; the real file is 1 line in 23,283.
TOLERANT = 0.5


def ingest(landing: Path, lake_dir: Path, registry: SchemaRegistry, share: float = TOLERANT) -> IngestReport:
    plan = IngestPlan.from_registry(registry, "verra")
    return IngestStage(
        finder=SnapshotFinder(landing, LandingFileNames("{prefix}_{date}.csv"), plan.tables_by_prefix()),
        loader=FileLoader(CsvFileReader(), HeaderMatcher(), RejectBudget(share)),
        lake=LocalLake(lake_dir, TABLE_FILE, MANIFEST_FILE),
        plan=plan,
    ).run()


def rows(lake_dir: Path, table: str) -> list[dict[str, Any]]:
    path = lake_dir / "bronze" / table / f"snapshot_date={FIXTURE_DAY}" / "data.parquet"
    return pq.read_table(path).to_pylist()


def columns(lake_dir: Path, table: str) -> list[str]:
    path = lake_dir / "bronze" / table / f"snapshot_date={FIXTURE_DAY}" / "data.parquet"
    return list(pq.read_schema(path).names)


def manifest(lake_dir: Path) -> dict[str, Any]:
    return json.loads(
        (lake_dir / "_manifests" / f"snapshot_date={FIXTURE_DAY}" / "ingest_verra.json").read_text()
    )


def test_loads_a_snapshot_with_a_different_date_into_bronze(
    landing: Path, tmp_path: Path, registry: SchemaRegistry
) -> None:
    report = ingest(landing, tmp_path / "lake", registry)

    assert report.snapshot_date == FIXTURE_DAY
    assert [(f.table, f.rows_read, f.rows_accepted, f.rows_rejected) for f in report.files] == [
        ("cancellations", 1, 1, 0),
        ("issuances", 2, 2, 0),
        ("retirements", 3, 2, 1),
    ]


def test_writes_columns_in_schema_order(landing: Path, tmp_path: Path, registry: SchemaRegistry) -> None:
    ingest(landing, tmp_path / "lake", registry)

    for table in ("issuances", "retirements", "cancellations", "rejected_records"):
        assert columns(tmp_path / "lake", table) == list(registry.table("bronze", table).column_names)


def test_keeps_values_exactly_as_delivered_with_their_lineage(
    landing: Path, tmp_path: Path, registry: SchemaRegistry
) -> None:
    ingest(landing, tmp_path / "lake", registry)
    retirements_file = landing / file_name("VerraRetirements")

    first, undated = rows(tmp_path / "lake", "retirements")

    assert first["retirement_reason_details"] == "Retired on behalf of Acme\nfor 2010"
    assert undated["retirement_date"] == "", "bronze keeps a blank as delivered; silver decides what it means"
    assert (first["_source_file"], first["_source_line"], undated["_source_line"]) == (
        retirements_file.name,
        2,
        4,
    )
    assert first["_file_sha256"] == hashlib.sha256(retirements_file.read_bytes()).hexdigest()
    assert first["_snapshot_date"] == FIXTURE_DAY


def test_puts_the_cut_off_record_in_its_systems_quarantine_table(
    landing: Path, tmp_path: Path, registry: SchemaRegistry
) -> None:
    ingest(landing, tmp_path / "lake", registry)

    [quarantined] = rows(tmp_path / "lake", "rejected_records")

    assert quarantined["target_table"] == "retirements"
    assert quarantined["_source_line"] == 5
    assert "probably cut off" in quarantined["reason"]
    assert quarantined["raw_text"].startswith("Verified Carbon Standard,28 Jul 2023")


def test_the_manifest_records_the_source_system_and_schema_version(
    landing: Path, tmp_path: Path, registry: SchemaRegistry
) -> None:
    ingest(landing, tmp_path / "lake", registry)

    record = manifest(tmp_path / "lake")

    assert record["source_system"] == "verra"
    assert record["schema_fingerprint"] == registry.fingerprint()
    assert record["quarantine"]["rows"] == 1


def test_running_twice_gives_identical_tables_and_manifest(
    landing: Path, tmp_path: Path, registry: SchemaRegistry
) -> None:
    lake_dir = tmp_path / "lake"
    ingest(landing, lake_dir, registry)
    first = {table: rows(lake_dir, table) for table in ("issuances", "retirements", "rejected_records")}
    first_manifest = manifest(lake_dir)

    ingest(landing, lake_dir, registry)

    assert {table: rows(lake_dir, table) for table in first} == first
    assert manifest(lake_dir) == first_manifest


def test_writes_nothing_when_one_file_breaks_the_schema(
    landing: Path, tmp_path: Path, registry: SchemaRegistry
) -> None:
    header = tuple(name for name in ISSUANCE_HEADER if name != "Units")
    write_csv(landing / file_name("VerraIssuances"), header, [row[:10] + row[11:] for row in ISSUANCE_ROWS])

    with pytest.raises(SchemaMismatchError, match="units"):
        ingest(landing, tmp_path / "lake", registry)

    assert not (tmp_path / "lake").exists(), (
        "no table may be written when any file in the snapshot is rejected"
    )


def test_the_default_budget_stops_a_file_that_is_largely_unreadable(
    landing: Path, tmp_path: Path, registry: SchemaRegistry
) -> None:
    with pytest.raises(RejectBudgetExceededError, match=re.escape("VerraRetirements_2030-01-15.csv")):
        ingest(landing, tmp_path / "lake", registry, share=0.01)


def test_a_file_lacking_an_optional_column_still_loads_with_it_empty(
    landing: Path, tmp_path: Path, registry: SchemaRegistry
) -> None:
    keep = [i for i, name in enumerate(RETIREMENT_HEADER) if name != "Region"]
    write_csv(
        landing / file_name("VerraRetirements"),
        [RETIREMENT_HEADER[i] for i in keep],
        [[row[i] for i in keep] for row in RETIREMENT_ROWS],
    )

    report = ingest(landing, tmp_path / "lake", registry)

    assert {row["region"] for row in rows(tmp_path / "lake", "retirements")} == {None}
    assert "lacks optional columns, left empty: region" in report.files[2].findings()


# Changing the schema changes the output, with no code change.


def test_an_alias_added_in_json_loads_a_renamed_header(landing: Path, tmp_path: Path) -> None:
    renamed = ["Quantity Retired" if name == "Retirement QTY" else name for name in RETIREMENT_HEADER]
    write_csv(landing / file_name("VerraRetirements"), renamed, RETIREMENT_ROWS)
    schema = copy_schema(tmp_path)
    with pytest.raises(SchemaMismatchError, match="retirement_qty"):
        ingest(landing, tmp_path / "lake", SchemaRegistry.load(schema))

    edit_json(
        schema / "bronze" / "retirements.json",
        lambda doc: next(c for c in doc["columns"] if c["name"] == "retirement_qty").update(
            aliases=["Quantity Retired"]
        ),
    )
    ingest(landing, tmp_path / "lake", SchemaRegistry.load(schema))

    assert [row["retirement_qty"] for row in rows(tmp_path / "lake", "retirements")] == ["100", "10"]


def remove_verifier(doc: Any) -> None:
    doc.update(columns=[column for column in doc["columns"] if column["name"] != "verifier"])


def remove_verifier_and_drop_unknown_columns(doc: Any) -> None:
    remove_verifier(doc)
    doc["unknown_columns"] = "drop"


def test_a_column_removed_from_json_is_kept_at_the_end_by_default(landing: Path, tmp_path: Path) -> None:
    schema = copy_schema(tmp_path)
    edit_json(schema / "bronze" / "issuances.json", remove_verifier)

    report = ingest(landing, tmp_path / "lake", SchemaRegistry.load(schema))

    assert columns(tmp_path / "lake", "issuances")[-1] == "verifier", "delivered data is never lost silently"
    assert "has columns the schema does not know, kept as text: verifier" in report.files[1].findings()


def test_a_column_removed_from_json_disappears_when_the_table_drops_unknown_columns(
    landing: Path, tmp_path: Path
) -> None:
    schema = copy_schema(tmp_path)
    edit_json(schema / "bronze" / "issuances.json", remove_verifier_and_drop_unknown_columns)

    report = ingest(landing, tmp_path / "lake", SchemaRegistry.load(schema))

    assert "verifier" not in columns(tmp_path / "lake", "issuances")
    assert "has columns the schema does not declare, left out: verifier" in report.files[1].findings()
