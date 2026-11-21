"""Tiny Verra files with the same quirks as the real exports, for tests to build on.

The fixture snapshot is dated 2030-01-15 on purpose, to prove nothing depends
on the 2026-11-17 snapshot that ships with the repository.
"""

from __future__ import annotations

import csv
import io
import json
import shutil
from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path
from typing import Any

FIXTURE_DAY = date(2030, 1, 15)
REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = REPO_ROOT / "schema"
REAL_CONFIG = REPO_ROOT / "config" / "pipeline.json"
TABLES_BY_PREFIX = {
    "VerraIssuances": "issuances",
    "VerraRetirements": "retirements",
    "VerraCancelled": "cancellations",
}

ISSUANCE_HEADER = (
    "Program",
    "Issuance Date",
    "Project ID",
    "Project Name",
    "Sectoral Scope",
    "Methodology",
    "Additional Certifications/Labels",
    "Sustainable Development Contributions",
    "Vintage",
    "Serial Number",
    "Units",
    "Unit Type",
    "Verifier",
    "Region",
    "Country",
    "State/Province",
    "Validation Status",
    "Validation Issues",
)
RETIREMENT_HEADER = (
    "Program",
    "Retirement Date",
    "Project ID",
    "Project Name",
    "Sectoral Scope",
    "Methodology",
    "Additional Certifications/Labels",
    "Sustainable Development Contributions",
    "Vintage",
    "Serial Number",
    "Retirement QTY",
    "Unit Type",
    "Region",
    "Country",
    "State/Province",
    "Beneficial Owner",
    "Retirement Reason",
    "Retirement Reason Details",
    "Validation Status",
    "Validation Issues",
)
CANCELLATION_HEADER = (
    "Program",
    "Cancellation Date",
    "Project ID",
    "Project Name",
    "Sectoral Scope",
    "Methodology",
    "Additional Certifications/Labels",
    "Sustainable Development Contributions",
    "Vintage",
    "Serial Number",
    "Cancellation QTY",
    "Unit Type",
    "Region",
    "Country",
    "State/Province",
    "Cancellation Reason",
    "Cancellation Reason Details",
)

VCS = "Verified Carbon Standard"
ENERGY = "Energy industries (renewable/non-renewable sources)"
WIND = "7.25 MW wind energy project"
LANDFILL = "Landfill Gas, Combustion Project"

ISSUANCE_ROWS = (
    (
        VCS,
        "19 Mar 2009",
        "1",
        WIND,
        ENERGY,
        "AMS-I.D. (Version NA)",
        "",
        "",
        "2006",
        "3-17361-26434-VCU-003-APX-IN-1-1-01042006-31122006-0",
        "9074",
        "VCU",
        "SGS",
        "Asia",
        "India",
        "Tamilnadu",
        "PASS",
        "",
    ),
    (
        VCS,
        "05 Oct 2012",
        "5",
        LANDFILL,
        f"{ENERGY}, Waste handling and disposal",
        "ACM0001 (Version NA)",
        "",
        "",
        "2011",
        "2456-104951535-104966817-VCU-025-APX-US-13-5-01012011-31122011-0",
        "15283",
        "VCU",
        "Tuev Sued",
        "North America",
        "United States of America",
        "PA",
        "PASS",
        "",
    ),
)
RETIREMENT_ROWS = (
    (
        VCS,
        "17 Nov 2010",
        "1",
        WIND,
        ENERGY,
        "AMS-I.D. (Version NA)",
        "",
        "",
        "2006",
        "3-17361-17460-VCU-003-APX-IN-1-1-01042006-31122006-0",
        "100",
        "VCU",
        "Asia",
        "India",
        "Tamilnadu",
        "Acme Ltd",
        "Other",
        "Retired on behalf of Acme\nfor 2010",
        "PASS",
        "",
    ),
    (
        VCS,
        "",
        "1",
        WIND,
        ENERGY,
        "AMS-I.D. (Version NA)",
        "",
        "",
        "2006",
        "3-17461-17470-VCU-003-APX-IN-1-1-01042006-31122006-0",
        "10",
        "VCU",
        "Asia",
        "India",
        "Tamilnadu",
        "",
        "",
        "",
        "FLAG",
        "missing Retirement Date",
    ),
)
CUT_OFF_RETIREMENT = f"{VCS},28 Jul 2023,1,{WIND},{ENERGY},AMS-I.D. (Version NA),,,"
CANCELLATION_ROWS = (
    (
        VCS,
        "01-Apr-09",
        "5",
        LANDFILL,
        ENERGY,
        "ACM0001 (Version NA)",
        "",
        "",
        "2011",
        "2456-104951535-104951634-VCU-025-APX-US-13-5-01012011-31122011-0",
        "100",
        "VCU",
        "North America",
        "United States of America",
        "PA",
        "Other",
        "",
    ),
)


def csv_line(fields: Sequence[str]) -> str:
    """One CSV record without its line ending, quoted the way the Verra exports quote."""
    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="").writerow(fields)
    return buffer.getvalue()


def write_csv(
    path: Path,
    header: Sequence[str],
    rows: Sequence[Sequence[str]],
    *,
    ending: str = "\n",
    bom: bool = False,
    trailing: str | None = None,
) -> Path:
    """Write a CSV file; `trailing` is a raw last line written without a final newline."""
    lines = [csv_line(header), *(csv_line(row) for row in rows)]
    text = ending.join(lines) + ending
    if trailing is not None:
        text += trailing
    path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8"))
    return path


def file_name(prefix: str, day: date = FIXTURE_DAY) -> str:
    return f"{prefix}_{day.isoformat()}.csv"


def write_config(
    folder: Path, landing: Path, schema: Path = SCHEMA_DIR, max_rejected_share: float = 0.5
) -> Path:
    """A copy of the real config whose landing folder and schema are the given ones, and whose lake and
    warehouse live in `folder`. The default reject budget is generous because the fixture files are tiny."""
    config = json.loads(REAL_CONFIG.read_text())
    config.pop("$schema")
    config["root"] = "."
    config["sources"]["verra"]["landing"] = str(landing)
    config["paths"] = {"schema": str(schema), "lake": "lake", "warehouse": "warehouse/verra.duckdb"}
    config["ingest"]["max_rejected_share"] = max_rejected_share
    path = folder / "pipeline.json"
    path.write_text(json.dumps(config, indent=2))
    return path


def copy_schema(folder: Path) -> Path:
    """A private copy of the real schema folder, safe for a test to edit."""
    return Path(shutil.copytree(SCHEMA_DIR, folder / "schema"))


def edit_json(path: Path, change: Callable[[Any], None]) -> None:
    """Load a JSON file, let `change` modify it in place, and save it."""
    document = json.loads(path.read_text())
    change(document)
    path.write_text(json.dumps(document, indent=2))
