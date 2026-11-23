from datetime import date
from pathlib import Path

import pytest

from tests.verra_files import REPO, write_snapshot
from verra_pipeline.cli import main


@pytest.fixture
def settings(tmp_path: Path) -> Path:
    """A copy of pipeline.toml in a temporary folder, so its relative paths (landing and lake) both
    land in that folder. The budget is generous because the fixture files are tiny."""
    path = tmp_path / "pipeline.toml"
    text = (REPO / "pipeline.toml").read_text(encoding="utf-8")
    path.write_text(text.replace("max_rejected_share = 0.01", "max_rejected_share = 0.5"), encoding="utf-8")
    write_snapshot(tmp_path / "data" / "landing")
    return path


def test_build_reports_what_it_loaded_and_query_reads_it(
    settings: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--config", str(settings), "build"]) == 0
    report = capsys.readouterr().out
    assert "Snapshot 2030-01-15" in report
    assert "line 5 quarantined" in report

    sql = (
        "select string_agg(_source_line::varchar, '-' order by _source_line) as lines from bronze.retirements"
    )
    assert main(["--config", str(settings), "query", sql]) == 0
    assert "2-4" in capsys.readouterr().out


def test_query_reads_the_newest_finished_snapshot(settings: Path, capsys: pytest.CaptureFixture[str]) -> None:
    for day in (date(2030, 1, 14), date(2030, 1, 16)):
        write_snapshot(settings.parent / "data" / "landing", day)
    for day in ("2030-01-15", "2030-01-14", "2030-01-16"):
        assert main(["--config", str(settings), "build", "--snapshot", day]) == 0
    # as if the 2030-01-16 build had stopped before its last step
    (settings.parent / "lake" / "_manifests" / "snapshot_date=2030-01-16" / "ingest.json").unlink()
    capsys.readouterr()

    sql = "select distinct _snapshot_date::varchar as day from bronze.issuances"
    assert main(["--config", str(settings), "query", sql]) == 0
    shown = capsys.readouterr().out
    assert "2030-01-15" in shown
    assert "2030-01-14" not in shown, "the newest snapshot, not the last one built"
    assert "2030-01-16" not in shown, "an unfinished snapshot stays hidden"


def test_an_error_is_one_clear_line(settings: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--config", str(settings), "build", "--snapshot", "2030-01-16"]) == 1
    landing = settings.resolve().parent / "data" / "landing"
    assert capsys.readouterr().err == f"error: no files dated 2030-01-16 in {landing}\n"

    # the lake can't go inside a file: the operating system's error comes out as one line too
    assert main(["--config", str(settings), "build", "--lake", str(settings)]) == 1
    error = capsys.readouterr().err
    assert error.startswith("error: [Errno")
    assert error.count("\n") == 1


def test_query_before_any_build_says_what_to_do(settings: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--config", str(settings), "query", "select 1"]) == 1
    assert "run `verra build` first" in capsys.readouterr().err


def test_a_bad_config_is_one_clear_line(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--config", str(tmp_path / "nope.toml"), "build"]) == 1
    assert "cannot read the config" in capsys.readouterr().err

    wrong = tmp_path / "wrong.toml"
    text = (REPO / "pipeline.toml").read_text(encoding="utf-8")
    wrong.write_text(text.replace("= 0.01", '= "1%"'), encoding="utf-8")
    assert main(["--config", str(wrong), "build"]) == 1
    assert "has a setting of the wrong type" in capsys.readouterr().err
