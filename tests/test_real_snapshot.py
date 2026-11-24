"""The snapshot that ships with the repository gives the numbers worked out in the data analysis.
Skipped when its files are not in data/landing, e.g. after a reviewer swaps in their own snapshot."""

import dataclasses
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from tests.verra_files import REPO
from verra_pipeline import PipelineError
from verra_pipeline.cli import build
from verra_pipeline.config import load
from verra_pipeline.ingest import find_snapshot
from verra_pipeline.lake import connect

SNAPSHOT = date(2026, 11, 17)
LANDING = REPO / "data" / "landing"


@pytest.mark.skipif(
    not (LANDING / f"VerraRetirements_{SNAPSHOT}.csv").exists(),
    reason="the 2026-11-17 files are not in data/landing",
)
def test_the_shipped_snapshot_gives_the_reference_numbers(tmp_path: Path) -> None:
    config = dataclasses.replace(load(REPO / "pipeline.toml"), landing=LANDING, lake=tmp_path / "lake")

    manifest = build(config, SNAPSHOT)

    assert manifest["credits"] == {
        "issued": 198_511_826,
        "retired": 56_564_196,
        "cancelled": 6_123_377,
        "available": 135_824_253,
    }
    assert {
        c["check_name"]: (c["failing_rows"], c["failing_credits"])
        for c in manifest["checks"]
        if not c["passed"]
    } == {
        "records quarantined: unreadable lines in the raw files": (1, 0),
        "events with no readable date": (19, 209_992),
        "retired or cancelled before the batch was issued": (20, 453_415),
        "retired credits with no named owner": (7_390, 39_846_198),
    }
    with connect(config.lake) as con:
        assert con.sql("SELECT count(*) FROM gold.dim_project").fetchall() == [(250,)]
        assert con.sql(
            "SELECT count(*) FILTER (WHERE retired > 0), count(*) FILTER (WHERE cancelled > 0) "
            "FROM gold.mart_project_balance"
        ).fetchall() == [(110, 33)]
        assert con.sql(
            "SELECT sum(issued) FROM gold.mart_vintage_activity WHERE vintage_start <> vintage_end"
        ).fetchall() == [(33_573_921,)]
        # the most common country of a project that issued in three (F19)
        assert con.sql("SELECT country FROM gold.dim_project WHERE project_id = 4151").fetchall() == [
            ("Rwanda",)
        ]
        # only the repair of mis-encoded names (StÃ¤dtische) merges this owner's two spellings
        stadtische = con.sql(
            "SELECT DISTINCT owner_rank, owner_credits FROM gold.mart_top_retirers "
            "WHERE owner_name = 'Städtische Werke AG, Königstor 3-13, 34117 Kassel'"
        ).fetchall()
        assert stadtische == [(7, 299_776)]
        top = con.sql(
            "SELECT DISTINCT owner_rank, owner_name, owner_credits FROM gold.mart_top_retirers "
            "WHERE owner_rank <= 3 ORDER BY owner_rank"
        ).fetchall()
    assert top == [
        (1, "Interface, Inc.", 745_954),
        (2, "Brisbane City Council", 712_027),
        (3, "Delta Air Lines", 644_713),
    ]


def newest_in_landing() -> date | None:
    try:
        return find_snapshot(load(REPO / "pipeline.toml"))[0]
    except PipelineError:  # no complete snapshot at all
        return None


@pytest.mark.skipif(
    newest_in_landing() != SNAPSHOT,
    reason="the analysis reads the newest snapshot in data/landing, and that isn't 2026-11-17",
)
def test_the_data_analysis_still_prints_the_numbers_the_docs_quote() -> None:
    printed = ""
    for script in sorted((REPO / "analysis").glob("*.py")):
        if script.name != "common.py":
            result = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
            assert result.returncode == 0, f"{script.name} failed:\n{result.stderr}"
            printed += result.stdout

    for number in (
        "198511826",  # issued, and then retired, cancelled and available
        "56564196",
        "6123377",
        "135824253",
        "34832",  # matches when serial ranges alone are compared: the trap
        "453415",  # credits retired before their batch was issued
        "39846198",  # retired credits with no owner
        "745954",  # Interface, Inc., the largest retirer once its spellings are merged
    ):
        assert number in printed, number
