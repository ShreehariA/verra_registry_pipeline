"""Shared fixtures."""

from pathlib import Path

import pytest

from tests.verra_files import (
    CANCELLATION_HEADER,
    CANCELLATION_ROWS,
    CUT_OFF_RETIREMENT,
    ISSUANCE_HEADER,
    ISSUANCE_ROWS,
    RETIREMENT_HEADER,
    RETIREMENT_ROWS,
    SCHEMA_DIR,
    file_name,
    write_csv,
)
from verra_pipeline.schema import SchemaRegistry


@pytest.fixture
def landing(tmp_path: Path) -> Path:
    """A landing folder holding one complete snapshot with the real exports' quirks:
    a byte-order mark, a line break inside a quoted field and a cut-off last record
    in retirements, and CRLF line endings in cancellations."""
    folder = tmp_path / "landing"
    folder.mkdir()
    write_csv(folder / file_name("VerraIssuances"), ISSUANCE_HEADER, ISSUANCE_ROWS)
    write_csv(
        folder / file_name("VerraRetirements"),
        RETIREMENT_HEADER,
        RETIREMENT_ROWS,
        bom=True,
        trailing=CUT_OFF_RETIREMENT,
    )
    write_csv(folder / file_name("VerraCancelled"), CANCELLATION_HEADER, CANCELLATION_ROWS, ending="\r\n")
    return folder


@pytest.fixture(scope="session")
def registry() -> SchemaRegistry:
    """The real schema folder, loaded once for the whole test run."""
    return SchemaRegistry.load(SCHEMA_DIR)
