from pathlib import Path

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

APP = str(REPO / "dashboard" / "app.py")


@pytest.fixture
def app(config: Config, monkeypatch: pytest.MonkeyPatch) -> AppTest:
    """The dashboard, reading a lake built from the fixture snapshot."""
    build(config)
    monkeypatch.setenv("VERRA_LAKE", str(config.lake))
    return AppTest.from_file(APP, default_timeout=60)


def test_the_headline_numbers_are_the_models_totals(app: AppTest) -> None:
    app.run()

    assert not app.exception
    assert {metric.label: metric.value for metric in app.metric} == {
        "Issued": "24,357",
        "Retired": "110",
        "Cancelled": "100",
        "Available": "24,147",
        "Projects": "2",
    }


VIEWS = ["Projects", "Vintages", "Retirers", "Over time", "Data quality"]


@pytest.mark.parametrize("view", VIEWS)
def test_every_view_renders(app: AppTest, view: str) -> None:
    app.run()

    app.radio(key="view").set_value(view).run()

    assert not app.exception
    assert app.subheader, "each view starts with the question it answers"


def test_an_empty_lake_says_what_to_do(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VERRA_LAKE", str(tmp_path / "lake"))
    app = AppTest.from_file(APP, default_timeout=60)

    app.run()

    assert [error.value for error in app.error] == [
        f"nothing has been built in {tmp_path / 'lake'} yet; run `verra build` first"
    ]


def test_every_view_stays_up_without_dates_or_owners(config: Config, monkeypatch: pytest.MonkeyPatch) -> None:
    blank = {"Issuance Date", "Retirement Date", "Cancellation Date", "Beneficial Owner"}
    exports = [
        ("VerraIssuances", ISSUANCE_HEADER, ISSUANCE_ROWS),
        ("VerraRetirements", RETIREMENT_HEADER, RETIREMENT_ROWS),
        ("VerraCancelled", CANCELLATION_HEADER, CANCELLATION_ROWS),
    ]
    for prefix, header, rows in exports:
        emptied = [
            ["" if column in blank else value for column, value in zip(header, row, strict=True)]
            for row in rows
        ]
        (config.landing / f"{prefix}_{DAY}.csv").write_bytes(csv_bytes(header, emptied))
    build(config)
    monkeypatch.setenv("VERRA_LAKE", str(config.lake))
    app = AppTest.from_file(APP, default_timeout=60)
    app.run()

    for view in VIEWS:
        app.radio(key="view").set_value(view).run()
        assert not app.exception, view
