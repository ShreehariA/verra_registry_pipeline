import re
from pathlib import Path
from typing import Any

import pytest

from tests.verra_files import (
    CANCELLATION_HEADER,
    ISSUANCE_HEADER,
    RETIREMENT_HEADER,
    copy_schema,
    edit_json,
)
from verra_pipeline.errors import SchemaDefinitionError
from verra_pipeline.ingest.bronze import GENERATED_VALUES
from verra_pipeline.json_formats import TABLE_FORMAT, format_document
from verra_pipeline.schema import SchemaRegistry
from verra_pipeline.schema.registry import layer_order

LINEAGE = ("_snapshot_date", "_source_file", "_source_line", "_file_sha256")


def test_the_real_schema_declares_the_bronze_layer(registry: SchemaRegistry) -> None:
    assert [table.name for table in registry.tables("bronze")] == [
        "cancellations",
        "issuances",
        "rejected_records",
        "retirements",
    ]
    assert registry.systems() == ("verra",)
    assert [table.name for table in registry.sourced_tables("verra")] == [
        "cancellations",
        "issuances",
        "retirements",
    ]
    assert registry.quarantine_table("verra").name == "rejected_records"


@pytest.mark.parametrize(
    ("table", "header"),
    [
        ("issuances", ISSUANCE_HEADER),
        ("retirements", RETIREMENT_HEADER),
        ("cancellations", CANCELLATION_HEADER),
    ],
)
def test_each_bronze_table_reads_every_real_header_then_adds_lineage(
    registry: SchemaRegistry, table: str, header: tuple[str, ...]
) -> None:
    spec = registry.table("bronze", table)

    assert [column.source_header for column in spec.source_columns()] == list(header)
    assert spec.column_names[-4:] == LINEAGE


def test_layers_come_in_data_flow_order_from_the_format() -> None:
    assert layer_order() == ("bronze", "silver", "gold")


def test_the_generated_values_the_code_fills_match_the_ones_the_format_allows() -> None:
    allowed = format_document(TABLE_FORMAT)["$defs"]["column"]["properties"]["generated"]["enum"]

    assert set(GENERATED_VALUES) == set(allowed)


def test_the_fingerprint_is_stable_and_changes_when_a_definition_changes(tmp_path: Path) -> None:
    schema = copy_schema(tmp_path)
    before = SchemaRegistry.load(schema).fingerprint()
    assert SchemaRegistry.load(schema).fingerprint() == before

    edit_json(schema / "bronze" / "issuances.json", lambda doc: doc.update(description="Changed."))

    assert SchemaRegistry.load(schema).fingerprint() != before


def first_column(doc: Any) -> Any:
    return doc["columns"][0]


BROKEN_TABLES = [
    (
        "unknown type",
        lambda doc: first_column(doc).update(type="strng"),
        "columns/0/type: 'strng' is not one of",
    ),
    (
        "no description",
        lambda doc: first_column(doc).pop("description"),
        "'description' is a required property",
    ),
    ("name differs from file", lambda doc: doc.update(name="retired"), "name is 'retired' but the file is"),
    ("unknown include", lambda doc: doc.update(include=["nope"]), "there is no shared/nope.json"),
    (
        "column repeated by include",
        lambda doc: first_column(doc).update(name="_source_file"),
        "columns appear more than once",
    ),
    ("header claimed twice", lambda doc: doc["columns"][1].update(aliases=["Program"]), "would feed both"),
    (
        "header and generated",
        lambda doc: first_column(doc).update(generated="source_file"),
        "columns/0: .* should not be valid under",
    ),
    ("keys in bronze", lambda doc: doc.update(primary_key=["program"]), "declares no keys"),
]


@pytest.mark.parametrize(
    ("case", "change", "message"), BROKEN_TABLES, ids=[case for case, _, _ in BROKEN_TABLES]
)
def test_a_broken_table_definition_stops_the_run_naming_the_file_and_reason(
    tmp_path: Path, case: str, change: Any, message: str
) -> None:
    schema = copy_schema(tmp_path)
    edit_json(schema / "bronze" / "retirements.json", change)

    with pytest.raises(SchemaDefinitionError, match=r"bronze/retirements\.json") as raised:
        SchemaRegistry.load(schema)
    assert re.search(message, str(raised.value)), str(raised.value)


def test_a_table_in_the_wrong_folder_is_refused(tmp_path: Path) -> None:
    schema = copy_schema(tmp_path)
    (schema / "silver").mkdir()
    (schema / "bronze" / "issuances.json").rename(schema / "silver" / "issuances.json")

    with pytest.raises(
        SchemaDefinitionError, match="layer is 'bronze' but the file is in the folder 'silver'"
    ):
        SchemaRegistry.load(schema)


def test_only_bronze_tables_may_read_from_files(tmp_path: Path) -> None:
    schema = copy_schema(tmp_path)
    (schema / "silver").mkdir()
    (schema / "silver" / "project.json").write_text(
        '{"layer": "silver", "name": "project", "description": "Projects.", "columns": ['
        '{"name": "project_id", "type": "integer", "description": "ID.", "source_header": "Project ID"}]}'
    )

    with pytest.raises(SchemaDefinitionError, match="only bronze tables read columns from files"):
        SchemaRegistry.load(schema)


def test_a_foreign_key_must_point_at_a_real_table(tmp_path: Path) -> None:
    schema = copy_schema(tmp_path)
    (schema / "silver").mkdir()
    (schema / "silver" / "batch.json").write_text(
        '{"layer": "silver", "name": "batch", "description": "Batches.", "columns": ['
        '{"name": "project_id", "type": "integer", "description": "ID."}], "foreign_keys": ['
        '{"columns": ["project_id"], "references": {"table": "silver.project", "columns": ["project_id"]}}]}'
    )

    missing_target = re.escape("references silver.project, which does not exist")
    with pytest.raises(SchemaDefinitionError, match=missing_target):
        SchemaRegistry.load(schema)


def test_each_source_system_needs_exactly_one_quarantine_table(tmp_path: Path) -> None:
    schema = copy_schema(tmp_path)
    second = schema / "bronze" / "more_rejects.json"
    second.write_text((schema / "bronze" / "rejected_records.json").read_text())
    edit_json(second, lambda doc: doc.update(name="more_rejects"))

    with pytest.raises(SchemaDefinitionError, match="needs exactly one quarantine table"):
        SchemaRegistry.load(schema)


def test_invalid_json_is_reported_with_its_line(tmp_path: Path) -> None:
    schema = copy_schema(tmp_path)
    (schema / "bronze" / "issuances.json").write_text('{"layer": "bronze",\n "name": }')

    with pytest.raises(SchemaDefinitionError, match=r"is not valid JSON: .* at line 2"):
        SchemaRegistry.load(schema)


def test_a_missing_schema_folder_is_reported(tmp_path: Path) -> None:
    with pytest.raises(SchemaDefinitionError, match="does not exist"):
        SchemaRegistry.load(tmp_path / "nowhere")
