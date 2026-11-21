import json
from pathlib import Path

import pytest

from tests.verra_files import REAL_CONFIG, REPO_ROOT, edit_json, write_config
from verra_pipeline.config import CONFIG_ENV_VAR, ConfigLocator, PipelineConfig
from verra_pipeline.errors import ConfigError


def test_the_real_config_loads_with_paths_resolved_from_its_root() -> None:
    config = PipelineConfig.load(REAL_CONFIG)

    assert config.source(None).name == "verra"
    assert config.source("verra").landing == REPO_ROOT / "data" / "landing"
    assert config.paths.schema == REPO_ROOT / "schema"
    assert config.paths.warehouse == REPO_ROOT / "warehouse" / "verra.duckdb"
    assert config.max_rejected_share == 0.01


def test_paths_do_not_depend_on_the_current_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)

    assert PipelineConfig.load(REAL_CONFIG).paths.lake == REPO_ROOT / "lake"


def test_the_locator_prefers_the_flag_then_the_environment_then_the_nearest_folder(tmp_path: Path) -> None:
    other = write_config(tmp_path, tmp_path)
    nested = REPO_ROOT / "src" / "verra_pipeline"

    assert ConfigLocator({}, nested).locate(other) == other
    assert ConfigLocator({CONFIG_ENV_VAR: str(other)}, nested).locate() == other
    assert ConfigLocator({}, nested).locate() == REAL_CONFIG


def test_the_locator_explains_what_to_do_when_nothing_is_found(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=f"pass --config FILE or set {CONFIG_ENV_VAR}"):
        ConfigLocator({}, tmp_path).locate()
    with pytest.raises(ConfigError, match="given by --config does not exist"):
        ConfigLocator({}, tmp_path).locate(tmp_path / "missing.json")


@pytest.mark.parametrize(
    ("key", "template", "message"),
    [
        (("lake", "table_file"), "{layer}/{table}/data.parquet", r"\{date\}, \{layer\}, \{table\}"),
        (("lake", "manifest_file"), "{stage}/{date}/{run}.json", r"\{date\}, \{stage\}"),
        (("warehouse", "history_view"), "{table}_history}", r"\{table\}"),
    ],
)
def test_templates_must_use_exactly_their_placeholders(
    tmp_path: Path, key: tuple[str, str], template: str, message: str
) -> None:
    file = write_config(tmp_path, tmp_path)
    edit_json(file, lambda doc: doc[key[0]].update({key[1]: template}))

    with pytest.raises(ConfigError, match=message):
        PipelineConfig.load(file)


def test_a_storage_uri_is_refused_clearly_until_the_cloud_step(tmp_path: Path) -> None:
    file = write_config(tmp_path, tmp_path)
    edit_json(file, lambda doc: doc["paths"].update(lake="gs://verra-lake"))

    with pytest.raises(ConfigError, match="is a storage URI"):
        PipelineConfig.load(file)


def test_a_config_breaking_the_format_names_the_place(tmp_path: Path) -> None:
    file = write_config(tmp_path, tmp_path)
    edit_json(file, lambda doc: doc["ingest"].update(max_rejected_share=2))

    with pytest.raises(ConfigError, match="ingest/max_rejected_share: 2 is greater than the maximum of 1"):
        PipelineConfig.load(file)


def test_choosing_a_source_system(tmp_path: Path) -> None:
    file = write_config(tmp_path, tmp_path)
    config = PipelineConfig.load(file)
    with pytest.raises(ConfigError, match="has no source 'acr'"):
        config.source("acr")

    edit_json(
        file, lambda doc: doc["sources"].update(acr={"landing": ".", "file_name": "{prefix}_{date}.csv"})
    )
    with pytest.raises(ConfigError, match="has several sources"):
        PipelineConfig.load(file).source(None)


def test_overrides_replace_single_values_for_one_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    config = PipelineConfig.load(REAL_CONFIG)

    changed = config.overridden(lake=Path("my-lake"), max_rejected_share=0.2)

    assert changed.paths.lake == tmp_path / "my-lake"
    assert changed.paths.schema == config.paths.schema
    assert changed.max_rejected_share == 0.2
    assert config.source("verra").with_landing(Path("drop")).landing == tmp_path / "drop"


def test_the_shipped_config_is_tidy_json() -> None:
    assert json.loads(REAL_CONFIG.read_text())["$schema"].endswith("formats/pipeline.schema.json")
