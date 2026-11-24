"""deploy/gcp.sh's safety rules, checked offline: fake gcloud and terraform commands log every call."""

import os
import shlex
import subprocess
from pathlib import Path

import pytest

from tests.verra_files import REPO


def dry_run(tmp_path: Path, command: str) -> tuple[list[str], list[list[str]]]:
    """Run `deploy/gcp.sh <command> --dry-run`; return the calls the fakes logged and the commands printed."""
    calls = tmp_path / "calls"
    for tool in ["gcloud", "terraform"]:
        fake = tmp_path / tool
        fake.write_text(f'#!/bin/sh\necho {tool} "$@" >> {calls}\n')
        fake.chmod(0o755)

    result = subprocess.run(
        ["bash", "deploy/gcp.sh", command, "--dry-run"],
        cwd=REPO,
        env={"PATH": f"{tmp_path}{os.pathsep}/usr/bin{os.pathsep}/bin", "GCP_PROJECT": "example-project"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    recorded = calls.read_text().splitlines() if calls.exists() else []
    return recorded, [shlex.split(line.removeprefix("+ ")) for line in result.stdout.splitlines()]


@pytest.mark.parametrize(("command", "plan"), [("up", "plan"), ("down", "plan -destroy")])
def test_a_dry_run_of_up_or_down_only_shows_terraforms_plan_for_the_project(
    tmp_path: Path, command: str, plan: str
) -> None:
    calls, _ = dry_run(tmp_path, command)

    assert calls == [
        "terraform -chdir=deploy init -input=false",
        f"terraform -chdir=deploy {plan} -var project=example-project -var region=us-central1",
    ]


def test_a_dry_run_of_run_calls_nothing_and_names_the_project_everywhere(tmp_path: Path) -> None:
    calls, printed = dry_run(tmp_path, "run")

    assert calls == []
    assert len(printed) == 3
    for words in printed:
        assert words[0] == "gcloud"
        assert words[words.index("--project") + 1] == "example-project", " ".join(words)


def test_it_refuses_without_a_project() -> None:
    result = subprocess.run(
        ["bash", "deploy/gcp.sh", "up", "--dry-run"],
        cwd=REPO,
        env={"PATH": f"/usr/bin{os.pathsep}/bin"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert result.stderr.startswith("error: set GCP_PROJECT")
