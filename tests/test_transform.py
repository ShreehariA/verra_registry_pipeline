import dataclasses
import shutil
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import pytest

from tests.verra_files import (
    CANCELLATION_HEADER,
    CANCELLATION_ROWS,
    DAY,
    ISSUANCE_HEADER,
    ISSUANCE_ROWS,
    REPO,
    RETIREMENT_HEADER,
    RETIREMENT_ROWS,
    csv_bytes,
)
from verra_pipeline import PipelineError, lake
from verra_pipeline.cli import build
from verra_pipeline.config import Config
from verra_pipeline.lake import connect, manifest_path
from verra_pipeline.transform import repair


@pytest.fixture(scope="module")
def macros() -> Iterator[duckdb.DuckDBPyConnection]:
    with duckdb.connect() as con:
        con.execute((REPO / "sql" / "macros.sql").read_text(encoding="utf-8"))
        yield con


def values(con: duckdb.DuckDBPyConnection, *expressions: str) -> tuple[Any, ...]:
    [row] = con.sql("SELECT " + ", ".join(expressions)).fetchall()
    return row


def gold(config: Config, sql: str) -> list[tuple[Any, ...]]:
    with connect(config.lake) as con:
        return con.sql(sql).fetchall()


def test_macros_read_the_formats_the_exports_use(macros: duckdb.DuckDBPyConnection) -> None:
    assert values(
        macros,
        "parse_date('19 Mar 2009')",
        "parse_date('01-Apr-09')",  # cancellations write a 2-digit year
        "parse_date('')",
        "parse_date('31 Feb 2009')",
    ) == (date(2009, 3, 19), date(2009, 4, 1), None, None)
    assert values(
        macros, "vintage_start('2007 - 2008')", "vintage_end('2007 - 2008')", "vintage_end('2013')"
    ) == (2007, 2008, 2013)
    new = "10026-172542403-172547402-VCS-VCU-263-VER-KE-14-1408-01012015-31122015-1"
    odd = "1247-54685576-54747845-VCU-008-CDC-IN-1-92-16062010_30062010-0"  # '_' between the dates
    assert values(
        macros,
        f"serial_part('{new}', 1)",
        f"serial_part('{new}', 2)",
        f"serial_part('{new}', 3)",
        f"serial_part('{odd}', 3)",
        "serial_part('not a serial', 1)",
    ) == (10026, 172542403, 172547402, 54747845, None)
    assert values(
        macros,
        "clean_text(' Yan' || chr(9) || 'Liu  ')",
        "clean_text('A' || chr(160) || 'B')",
        "clean_text(' ')",
    ) == ("Yan Liu", "A B", None)
    assert values(
        macros,
        "whole_number(' 24357 ')",
        "whole_number('12.5')",  # try_cast alone would read 13
        "whole_number('1,000')",
        "whole_number('-5')",
        "whole_number('')",
    ) == (24357, None, None, None, None)


@pytest.mark.parametrize(
    ("name", "key"),
    [
        ("Interface, Inc.", "interface"),
        ("INTERFACE INC", "interface"),
        ("Natura Cosméticos S.A.", "naturacosmeticos"),
        ("Chevron Petroleum Company S.A NIT 860.005.223-9", "chevronpetroleumcompanysanit8600052239"),
        ("南京玄武环境集团有限公司", "南京玄武环境集团有限公司"),  # not a-z, but not blank either
        ("_", "unspecified"),
        ("N/A", "unspecified"),
        (None, "unspecified"),
    ],
)
def test_owner_key_groups_spellings_of_one_owner(
    macros: duckdb.DuckDBPyConnection, name: str, key: str
) -> None:
    assert macros.execute("SELECT owner_key(?)", [name]).fetchall() == [(key,)]


def test_repair_fixes_mis_encoded_text_only() -> None:
    assert repair("StÃ¤dtische Werke, KÃ¶nigstor") == "Städtische Werke, Königstor"
    assert repair("Natura CosmÃ©ticos") == "Natura Cosméticos"
    assert repair("SÃO PAULO") == "SÃO PAULO", "real Portuguese stays as it is"
    assert repair("Städtische") == "Städtische"


def test_gold_adds_up_and_the_gate_reports_what_it_saw(config: Config) -> None:
    manifest = build(config)

    assert manifest["credits"] == {"issued": 24357, "retired": 110, "cancelled": 100, "available": 24147}
    assert gold(
        config, "SELECT project_id, issued, retired, cancelled, available FROM gold.mart_project_balance"
    ) == [
        (1, 9074, 110, 0, 8964),
        (5, 15283, 0, 100, 15183),
    ]
    assert {c["check_name"]: c["failing_rows"] for c in manifest["checks"] if not c["passed"]} == {
        "records quarantined: unreadable lines in the raw files": 1,
        "events with no readable date": 1,
        "retired credits with no named owner": 1,
        "retired or cancelled before the batch was issued": 1,  # cancelled 01-Apr-09, issued 05 Oct 2012
    }


def test_spellings_of_one_owner_become_one_owner(config: Config) -> None:
    second = list(RETIREMENT_ROWS[1])
    second[RETIREMENT_HEADER.index("Beneficial Owner")] = "ACME LIMITED "
    retirements = config.landing / f"VerraRetirements_{DAY}.csv"
    retirements.write_bytes(csv_bytes(RETIREMENT_HEADER, [RETIREMENT_ROWS[0], second]))

    build(config)

    assert gold(config, "SELECT owner_key, owner_name, spellings FROM gold.dim_beneficial_owner") == [
        ("acme", "Acme Ltd", "Acme Ltd | ACME LIMITED")  # named by the spelling with the most credits
    ]
    assert gold(config, "SELECT owner_rank, owner_credits FROM gold.mart_top_retirers") == [(1, 110)]


def with_value(row: tuple[str, ...], header: tuple[str, ...], column: str, value: str) -> list[str]:
    changed = list(row)
    changed[header.index(column)] = value
    return changed


FAILING: dict[str, tuple[bytes, str]] = {
    "a quantity below zero": (
        csv_bytes(ISSUANCE_HEADER, [with_value(ISSUANCE_ROWS[0], ISSUANCE_HEADER, "Units", "-5")]),
        "every quantity is a whole number above zero: 1 row",
    ),
    "a row delivered twice": (
        csv_bytes(ISSUANCE_HEADER, [*ISSUANCE_ROWS, ISSUANCE_ROWS[0]]),
        "no serial number appears twice in one export: 1 row",
    ),
}


@pytest.mark.parametrize("case", list(FAILING))
def test_a_failed_error_check_stops_the_build_before_anything_is_written(config: Config, case: str) -> None:
    issuances, message = FAILING[case]
    (config.landing / f"VerraIssuances_{DAY}.csv").write_bytes(issuances)

    with pytest.raises(PipelineError, match=f"quality gate failed, so nothing was written: {message}"):
        build(config)
    assert not config.lake.exists()


def test_blank_serial_numbers_and_vintages_are_reported_not_refused(config: Config) -> None:
    rows = [with_value(row, RETIREMENT_HEADER, "Serial Number", "") for row in RETIREMENT_ROWS]
    rows = [with_value(tuple(row), RETIREMENT_HEADER, "Vintage", "") for row in rows]
    (config.landing / f"VerraRetirements_{DAY}.csv").write_bytes(csv_bytes(RETIREMENT_HEADER, rows))

    manifest = build(config)

    failing = {c["check_name"]: c["failing_rows"] for c in manifest["checks"] if not c["passed"]}
    assert failing["serial numbers that could not be read"] == 2
    assert failing["vintages that could not be read"] == 2


def test_a_rebuild_gives_byte_identical_files(config: Config) -> None:
    build(config)
    first = {path: path.read_bytes() for path in config.lake.rglob("*") if path.is_file()}

    build(config)

    assert {path: path.read_bytes() for path in config.lake.rglob("*") if path.is_file()} == first
    assert {path.relative_to(config.lake).parts[0] for path in first} == {
        "_manifests",
        "bronze",
        "silver",
        "gold",
    }


def test_the_batch_checks_catch_credits_used_twice_and_strays(config: Config) -> None:
    whole_batch = list(RETIREMENT_ROWS[1])  # retires the whole of batch 3, which the first row also draws on
    whole_batch[RETIREMENT_HEADER.index("Serial Number")] = (
        "3-17361-26434-VCU-003-APX-IN-1-1-01042006-31122006-0"
    )
    whole_batch[RETIREMENT_HEADER.index("Retirement QTY")] = "9074"
    (config.landing / f"VerraRetirements_{DAY}.csv").write_bytes(
        csv_bytes(RETIREMENT_HEADER, [RETIREMENT_ROWS[0], whole_batch])
    )
    stray = list(CANCELLATION_ROWS[0])  # batch 9999 was never issued
    stray[CANCELLATION_HEADER.index("Serial Number")] = "9999-1-100-VCU-001-TZ1-US-13-5-01012011-31122011-0"
    (config.landing / f"VerraCancelled_{DAY}.csv").write_bytes(
        csv_bytes(CANCELLATION_HEADER, [stray], "\r\n")
    )

    manifest = build(config)

    failing = {c["check_name"]: c["failing_rows"] for c in manifest["checks"] if not c["passed"]}
    assert failing["credits retired or cancelled twice (overlapping serial ranges)"] == 1
    assert failing["batches with more retired and cancelled than issued"] == 1
    assert failing["projects with a negative available balance"] == 1
    assert failing["retired or cancelled credits outside every issued batch"] == 1


def test_a_rebuild_hides_its_day_until_every_file_is_written(
    config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    build(config)
    write_parquet, written = lake.write_parquet, []

    def disk_full_on_the_second_file(rows: duckdb.DuckDBPyRelation, path: Path) -> None:
        written.append(path)
        if len(written) == 2:
            raise OSError("disk full")
        write_parquet(rows, path)

    monkeypatch.setattr(lake, "write_parquet", disk_full_on_the_second_file)
    with pytest.raises(OSError, match="disk full"):
        build(config)

    assert not manifest_path(config.lake, DAY).exists(), "half new, half old: hidden from readers"
    with pytest.raises(PipelineError, match="nothing has been built"):
        connect(config.lake)


def test_a_broken_sql_file_is_named_in_one_line(config: Config, tmp_path: Path) -> None:
    sql = shutil.copytree(REPO / "sql", tmp_path / "sql")
    (sql / "gold" / "mart_project_balance.sql").write_text("SELECT no_such_column FROM gold.dim_project")

    with pytest.raises(PipelineError, match=r"mart_project_balance\.sql failed: Binder Error") as error:
        build(dataclasses.replace(config, sql=sql))
    assert "\n" not in str(error.value)
    assert not config.lake.exists()
