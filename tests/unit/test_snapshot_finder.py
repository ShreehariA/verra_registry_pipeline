import re
from datetime import date
from pathlib import Path

import pytest

from tests.verra_files import TABLES_BY_PREFIX
from verra_pipeline.errors import IncompleteSnapshotError, SnapshotNotFoundError
from verra_pipeline.snapshot import LandingFileNames, SnapshotFinder

NOV_16, NOV_17, NOV_18 = date(2026, 11, 16), date(2026, 11, 17), date(2026, 11, 18)
NAMES = LandingFileNames("{prefix}_{date}.csv")


def touch(folder: Path, *names: str) -> None:
    for name in names:
        (folder / name).write_text("x")


def full_drop(day: date, names: LandingFileNames = NAMES) -> list[str]:
    return [names.name(prefix, day) for prefix in TABLES_BY_PREFIX]


def finder(folder: Path, names: LandingFileNames = NAMES) -> SnapshotFinder:
    return SnapshotFinder(folder, names, TABLES_BY_PREFIX)


def test_file_names_follow_the_template_both_ways() -> None:
    assert NAMES.name("VerraCancelled", NOV_17) == "VerraCancelled_2026-11-17.csv"
    assert NAMES.parse("VerraCancelled_2026-11-17.csv") == ("VerraCancelled", NOV_17)
    assert NAMES.parse("VerraCancelled_2026-13-45.csv") is None
    assert NAMES.parse("notes.txt") is None


def test_picks_the_newest_date_that_has_every_file(tmp_path: Path) -> None:
    touch(tmp_path, *full_drop(NOV_16), *full_drop(NOV_17), NAMES.name("VerraIssuances", NOV_18))

    snapshot = finder(tmp_path).find()

    assert snapshot.snapshot_date == NOV_17
    assert snapshot.file_for("cancellations") == tmp_path / "VerraCancelled_2026-11-17.csv"


def test_loads_the_date_it_is_asked_for(tmp_path: Path) -> None:
    touch(tmp_path, *full_drop(NOV_16), *full_drop(NOV_17))

    assert finder(tmp_path).find(NOV_16).snapshot_date == NOV_16


def test_a_requested_date_missing_a_file_is_incomplete(tmp_path: Path) -> None:
    touch(tmp_path, NAMES.name("VerraIssuances", NOV_17), NAMES.name("VerraRetirements", NOV_17))

    with pytest.raises(IncompleteSnapshotError, match=re.escape("VerraCancelled_2026-11-17.csv")):
        finder(tmp_path).find(NOV_17)


def test_a_requested_date_with_no_files_is_not_found(tmp_path: Path) -> None:
    touch(tmp_path, *full_drop(NOV_17))

    with pytest.raises(SnapshotNotFoundError, match="2026-11-18"):
        finder(tmp_path).find(NOV_18)


def test_says_what_it_found_when_no_date_is_complete(tmp_path: Path) -> None:
    touch(tmp_path, NAMES.name("VerraIssuances", NOV_17))

    with pytest.raises(SnapshotNotFoundError, match="2026-11-17 has 1 of 3"):
        finder(tmp_path).find()


def test_names_the_expected_files_when_the_folder_has_none(tmp_path: Path) -> None:
    with pytest.raises(SnapshotNotFoundError, match=re.escape("VerraIssuances_YYYY-MM-DD.csv")):
        finder(tmp_path).find()


def test_ignores_files_that_do_not_follow_the_template(tmp_path: Path) -> None:
    touch(
        tmp_path,
        *full_drop(NOV_17),
        "notes.txt",
        "VerraUnknown_2026-11-18.csv",
        "VerraIssuances_2026-13-45.csv",
        "VerraIssuances_2026-11-18.csv.bak",
    )

    assert finder(tmp_path).find().snapshot_date == NOV_17


def test_works_with_any_naming_template_from_the_config(tmp_path: Path) -> None:
    other = LandingFileNames("export-{date}-{prefix}.txt")
    touch(tmp_path, *full_drop(NOV_17, other))

    snapshot = finder(tmp_path, other).find()

    assert snapshot.file_for("issuances").name == "export-2026-11-17-VerraIssuances.txt"


def test_a_missing_landing_folder_is_not_found(tmp_path: Path) -> None:
    with pytest.raises(SnapshotNotFoundError, match="does not exist"):
        finder(tmp_path / "nowhere").find()
