from datetime import date
from pathlib import Path

import pytest

from verra_pipeline.errors import PipelineError
from verra_pipeline.lake import LocalLake, TableData
from verra_pipeline.schema import ColumnSpec, ColumnType
from verra_pipeline.warehouse import LocalWarehouse, ViewNames

OLD, NEW = date(2030, 1, 14), date(2030, 1, 15)
ID = ColumnSpec("project_id", ColumnType.TEXT, "ID.")
ADDED_LATER = ColumnSpec("verifier", ColumnType.TEXT, "Added to the schema on the 15th.")


def test_view_names_follow_the_config_templates(tmp_path: Path) -> None:
    lake = LocalLake(tmp_path, "{layer}/{table}/snapshot_date={date}/data.parquet", "{stage}_{date}.json")

    views = ViewNames("{table}_latest", "{table}_all").for_snapshot(lake, "bronze", ["issuances"], NEW)

    assert set(views) == {"issuances_latest", "issuances_all"}


def test_history_views_survive_a_column_added_to_the_schema_later(tmp_path: Path) -> None:
    lake = LocalLake(
        tmp_path / "lake", "{layer}/{table}/snapshot_date={date}/data.parquet", "{stage}_{date}.json"
    )
    lake.write_table("bronze", "issuances", OLD, TableData((ID,), (("1",),)))
    lake.write_table("bronze", "issuances", NEW, TableData((ID, ADDED_LATER), (("2", "SGS"),)))
    warehouse = LocalWarehouse(tmp_path / "verra.duckdb")

    warehouse.create_views(
        "bronze", ViewNames("{table}", "{table}_history").for_snapshot(lake, "bronze", ["issuances"], NEW)
    )

    result = warehouse.query("select project_id, verifier from bronze.issuances_history order by project_id")
    assert result.rows == (("1", None), ("2", "SGS"))


def test_refuses_names_that_are_not_safe_in_sql(tmp_path: Path) -> None:
    with pytest.raises(PipelineError, match="not a usable SQL name"):
        LocalWarehouse(tmp_path / "verra.duckdb").create_views("bronze", {"issuances; drop": tmp_path})
