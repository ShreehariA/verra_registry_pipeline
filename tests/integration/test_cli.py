from pathlib import Path

import pytest

from tests.verra_files import write_config
from verra_pipeline.cli import main
from verra_pipeline.config import CONFIG_ENV_VAR


def run(*arguments: str) -> int:
    return main(list(arguments))


def test_ingest_prints_a_summary_and_query_reads_the_result(
    landing: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = str(write_config(tmp_path, landing))

    assert run("ingest", "--config", config) == 0
    summary = capsys.readouterr().out
    assert "Source verra, snapshot 2030-01-15" in summary
    assert "line 5 quarantined" in summary

    assert run("query", "select count(*) as loaded from bronze.retirements", "--config", config) == 0
    assert capsys.readouterr().out.split()[-1] == "2"


def test_the_config_can_come_from_the_environment(
    landing: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(CONFIG_ENV_VAR, str(write_config(tmp_path, landing)))

    assert run("ingest") == 0
    assert "snapshot 2030-01-15" in capsys.readouterr().out


def test_flags_override_the_config_for_one_run(
    landing: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = str(write_config(tmp_path, tmp_path / "empty"))

    assert (
        run("ingest", "--config", config, "--landing", str(landing), "--lake", str(tmp_path / "other")) == 0
    )
    assert (tmp_path / "other" / "bronze" / "issuances").is_dir()


def test_schema_lists_the_tables_and_one_tables_columns(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = str(write_config(tmp_path, tmp_path))

    assert run("schema", "--config", config) == 0
    listing = capsys.readouterr().out
    assert "retirements" in listing
    assert "verra: VerraRetirements" in listing

    assert run("schema", "--table", "retirements", "--config", config) == 0
    columns = capsys.readouterr().out
    assert "header 'Retirement QTY' (required)" in columns
    assert "generated: source_line" in columns


def test_a_pipeline_error_is_one_readable_line(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = str(write_config(tmp_path, tmp_path / "missing"))

    assert run("ingest", "--config", config) == 1
    assert capsys.readouterr().err.startswith("error: the landing folder")


def test_query_before_any_ingest_explains_what_to_do(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = str(write_config(tmp_path, tmp_path))

    assert run("query", "select 1", "--config", config) == 1
    assert "run `verra ingest` first" in capsys.readouterr().err


def test_bad_sql_is_reported_not_crashed(
    landing: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = str(write_config(tmp_path, landing))
    run("ingest", "--config", config)

    assert run("query", "select nonsense from bronze.issuances", "--config", config) == 1
    assert capsys.readouterr().err.startswith("error: the query failed")
