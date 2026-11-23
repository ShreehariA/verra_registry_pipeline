import dataclasses
from pathlib import Path

import pytest

from tests.verra_files import REPO, write_snapshot
from verra_pipeline.config import Config, load


@pytest.fixture
def config(tmp_path: Path) -> Config:
    """The real pipeline.toml, reading a fixture snapshot and writing into a temporary folder. The reject
    budget is generous because the fixture files are tiny: retirements has one cut-off line in four."""
    return dataclasses.replace(
        load(REPO / "pipeline.toml"),
        landing=write_snapshot(tmp_path / "landing"),
        lake=tmp_path / "lake",
        max_rejected_share=0.5,
    )
