"""The dashboard, run with Streamlit's AppTest (no browser) on a lake built from the fixture snapshot."""

import importlib.util
from collections.abc import Collection
from pathlib import Path
from types import ModuleType

import duckdb
import pytest
from streamlit.testing.v1 import AppTest

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
from verra_pipeline.cli import build
from verra_pipeline.config import Config
from verra_pipeline.lake import connect, lock_down

APP = str(REPO / "dashboard" / "app.py")
PAGES = ["overview", "projects", "vintages", "retirers", "over_time", "data_quality", "sql"]


@pytest.fixture
def app(config: Config, monkeypatch: pytest.MonkeyPatch) -> AppTest:
    """The dashboard, reading a lake built from the fixture snapshot."""
    build(config)
    monkeypatch.setenv("VERRA_LAKE", str(config.lake))
    return AppTest.from_file(APP, default_timeout=60)


def open_page(app: AppTest, page: str) -> AppTest:
    app.run()
    return app.switch_page(f"app_pages/{page}.py").run()


def test_the_overview_leads_with_the_models_totals(app: AppTest) -> None:
    app.run()

    assert not app.exception
    assert [(metric.label, metric.value, metric.proto.help) for metric in app.metric] == [
        ("Credits issued", "24.4K", "24,357 credits")
    ]
    # the ledger bar: retired 110, cancelled 100 and available 24,147 of the 24,357 issued
    assert app.get("vega_lite_chart")[0].proto.alt == (
        "Of 24.4K credits issued, 0.5% are retired, 0.4% cancelled and 99.1% still available."
    )
    assert "**Retirers.** Acme Ltd retired the most: 100 credits. 9.1% of retired credits name no owner." in [
        link.value for link in app.page_link
    ]


@pytest.mark.parametrize("page", PAGES)
def test_every_page_renders(app: AppTest, page: str) -> None:
    open_page(app, page)

    assert not app.exception
    assert app.title, "each page starts with its title"


@pytest.mark.parametrize(("search", "found"), [("landfill", [5]), ("india", [1]), ("1", [1])])
def test_a_project_is_found_by_name_country_or_id(app: AppTest, search: str, found: list[int]) -> None:
    open_page(app, "projects")

    app.text_input(key="projects_search").input(search).run()

    assert app.dataframe[0].value["project_id"].tolist() == found


def test_the_sql_page_runs_queries_cuts_long_results_and_shows_errors(app: AppTest) -> None:
    open_page(app, "sql")
    assert len(app.dataframe[1].value) == 2, "it opens on an example: the 2 projects, largest first"

    app.text_area(key="sql_text").input("SELECT * FROM range(5000)")
    app.form_submit_button[0].click().run()
    assert len(app.dataframe[1].value) == 1_000
    cut = "More than 1,000 rows: the first 1,000 are shown. Narrow it with WHERE."
    assert app.caption[-1].value == cut

    app.text_area(key="sql_text").input("SELECT 1 AS one")
    app.form_submit_button[0].click().run()
    assert app.caption[-1].value.startswith("1 row in ")

    app.session_state["sql_tab"] = "History"
    app.run()
    assert app.caption[2].value == cut, "the history says the same as the result: not 1,001 rows"

    app.session_state["sql_tab"] = "Query"
    app.run()
    app.text_area(key="sql_text").input("SELECT * FROM read_csv('pyproject.toml')")
    app.form_submit_button[0].click().run()
    assert not app.exception
    assert app.error[0].value == "The query failed"
    assert "Permission Error" in app.code[0].value


def test_the_sql_editor_keeps_its_query_while_another_tab_is_open(app: AppTest) -> None:
    open_page(app, "sql")
    app.text_area(key="sql_text").input("SELECT 42 AS answer")
    app.form_submit_button[0].click().run()

    for tab in ["History", "Query"]:
        app.session_state["sql_tab"] = tab
        app.run()

    assert app.text_area(key="sql_text").value == "SELECT 42 AS answer"
    assert [entry["sql"] for entry in app.session_state["sql_history"]] == [
        "SELECT 42 AS answer",
        "SELECT project_name, issued, retired, cancelled, available\n"
        "FROM gold.mart_project_balance\nORDER BY issued DESC\nLIMIT 10",
    ], "only the two queries run: no empty one from an editor wiped by the tab switch"


def test_the_sql_navigator_finds_tables_by_their_columns(app: AppTest) -> None:
    open_page(app, "sql")

    app.text_input(key="sql_search").input("owner_key").run()

    assert app.dataframe[0].value["table_name"].tolist() == [
        "gold.dim_beneficial_owner",
        "gold.fct_credit_event",
        "gold.mart_top_retirers",
        "silver.retirements",
    ]


def common() -> ModuleType:
    """dashboard/common.py, which the pages import by its name."""
    spec = importlib.util.spec_from_file_location("common", REPO / "dashboard" / "common.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_names_from_the_registry_cannot_become_markdown() -> None:
    shared = common()

    assert shared.plain("[Claim credits](https://x.example)") == r"\[Claim credits\]\(https\://x\.example\)"
    assert shared.short("0x5298ee22D6B4EC1A8C62944BA63a8A197ee726e2") == "0x5298…26e2"
    assert shared.short("Interface, Inc.") == "Interface, Inc."
    assert shared.compact(198_511_826) == "198.5M"


@pytest.mark.parametrize(
    ("sql", "refused_with"),
    [
        ("SELECT * FROM read_csv('{repo}/pyproject.toml')", duckdb.PermissionException),  # reading any file
        ("COPY (SELECT 1) TO '{lake}/copied.csv'", duckdb.PermissionException),  # writing, even into the lake
        ("SET enable_external_access = true", duckdb.InvalidInputException),  # DuckDB never allows this back
        ("SET max_execution_time = 0", duckdb.InvalidInputException),  # the lock: no setting can be undone
        ("SELECT count(*) FROM range(1000000000000)", duckdb.InterruptException),  # a query that never ends
        (  # a sort too big for 256 MB: it would finish by spilling to disk, if there were a disk to spill to
            "SELECT max(x) FROM (SELECT hash(i) AS x FROM range(60000000) t(i) ORDER BY x LIMIT 60000000)",
            duckdb.OutOfMemoryException,
        ),
    ],
)
def test_sql_typed_by_anyone_touches_no_file_and_stops_in_time(
    config: Config, sql: str, refused_with: type[duckdb.Error]
) -> None:
    build(config)
    with connect(config.lake, copy=True) as con:
        lock_down(con, seconds=1)

        assert con.execute("SELECT count(*) FROM gold.dim_project").fetchall() == [(2,)]
        with pytest.raises(refused_with):
            con.execute(sql.format(repo=REPO, lake=config.lake)).fetchall()
    assert not (config.lake / "copied.csv").exists()


def test_an_empty_lake_says_what_to_do(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VERRA_LAKE", str(tmp_path / "lake"))
    app = AppTest.from_file(APP, default_timeout=60)

    app.run()

    assert [error.value for error in app.error] == [
        f"nothing has been built in {tmp_path / 'lake'} yet; run `verra build` first"
    ]


def snapshot_with(
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
    blank: Collection[str] = (),
    drop: Collection[str] = (),
) -> AppTest:
    """The dashboard on the fixture snapshot rewritten with some columns blanked, or dropped altogether."""
    exports = [
        ("VerraIssuances", ISSUANCE_HEADER, ISSUANCE_ROWS),
        ("VerraRetirements", RETIREMENT_HEADER, RETIREMENT_ROWS),
        ("VerraCancelled", CANCELLATION_HEADER, CANCELLATION_ROWS),
    ]
    for prefix, header, rows in exports:
        kept = [i for i, column in enumerate(header) if column not in drop]
        changed = [["" if header[i] in blank else row[i] for i in kept] for row in rows]
        (config.landing / f"{prefix}_{DAY}.csv").write_bytes(csv_bytes([header[i] for i in kept], changed))
    build(config)
    monkeypatch.setenv("VERRA_LAKE", str(config.lake))
    return AppTest.from_file(APP, default_timeout=60).run()


def pick(app: AppTest, table_key: str, row: int) -> None:
    """Pick a row of a table, as a click in the browser would (AppTest has no click for table rows)."""
    app.session_state[table_key] = {"selection": {"rows": [row], "columns": [], "cells": []}}
    app.run()


def test_every_page_stays_up_without_dates_or_owners(config: Config, monkeypatch: pytest.MonkeyPatch) -> None:
    app = snapshot_with(
        config,
        monkeypatch,
        blank={"Issuance Date", "Retirement Date", "Cancellation Date", "Beneficial Owner"},
    )

    for page in PAGES:
        app.switch_page(f"app_pages/{page}.py").run()
        assert not app.exception, page


def test_a_picked_project_and_a_picked_table_open(app: AppTest) -> None:
    open_page(app, "projects")
    pick(app, "projects_table ", 0)  # the table's key holds its search, here none; row 0 is the largest

    assert not app.exception
    assert app.subheader[-1].value == "Landfill Gas, Combustion Project"
    assert any(caption.value.startswith("Project 5, United States of America. ") for caption in app.caption)

    app.switch_page("app_pages/sql.py").run()
    pick(app, "sql_navigator ", 2)  # gold first, by name: dim_beneficial_owner, dim_project, fct_credit_event
    for tab in ("Table", "Diagram"):
        app.session_state["sql_tab"] = tab
        app.run()
        assert not app.exception, tab
        if tab == "Table":
            assert app.subheader[0].value == "gold.fct_credit_event"


def test_a_picked_project_leaves_out_details_the_snapshot_lacks(
    config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = snapshot_with(config, monkeypatch, drop={"Country", "Sectoral Scope"})  # both optional
    open_page(app, "projects")

    pick(app, "projects_table ", 0)

    assert "Project 5." in [caption.value for caption in app.caption], "not 'Project 5, None. None.'"


def test_over_time_counts_every_undated_event(config: Config, monkeypatch: pytest.MonkeyPatch) -> None:
    app = snapshot_with(
        config, monkeypatch, blank={"Issuance Date"}
    )  # the fixture has one undated retirement
    open_page(app, "over_time")

    captions = [caption.value for caption in app.caption]
    assert (
        "2 issuances, 1 retirement (24,367 credits) have no date, so they aren't on this chart. "
        "They count in every total." in captions
    )

    app.session_state["over_time_show"] = "Running total"
    app.run()
    assert (
        "The gap between the two lines is the credits still available, apart from the undated events "
        "below, which have no year." in [caption.value for caption in app.caption]
    )
