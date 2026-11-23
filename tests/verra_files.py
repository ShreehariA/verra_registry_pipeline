"""Tiny Verra files with the real exports' quirks, dated 2030-01-15 on purpose:
nothing may depend on the snapshot that ships with the repository."""

import codecs
import csv
import io
from collections.abc import Sequence
from datetime import date
from pathlib import Path

DAY = date(2030, 1, 15)
REPO = Path(__file__).resolve().parents[1]

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
    (VCS, "19 Mar 2009", "1", WIND, ENERGY, "AMS-I.D. (Version NA)", "", "", "2006",
     "3-17361-26434-VCU-003-APX-IN-1-1-01042006-31122006-0", "9074", "VCU", "SGS", "Asia", "India",
     "Tamilnadu", "PASS", ""),
    (VCS, "05 Oct 2012", "5", LANDFILL, f"{ENERGY}, Waste handling and disposal", "ACM0001 (Version NA)", "",
     "", "2011", "2456-104951535-104966817-VCU-025-APX-US-13-5-01012011-31122011-0", "15283", "VCU",
     "Tuev Sued", "North America", "United States of America", "PA", "PASS", ""),
)  # fmt: skip
RETIREMENT_ROWS = (
    (VCS, "17 Nov 2010", "1", WIND, ENERGY, "AMS-I.D. (Version NA)", "", "", "2006",
     "3-17361-17460-VCU-003-APX-IN-1-1-01042006-31122006-0", "100", "VCU", "Asia", "India", "Tamilnadu",
     "Acme Ltd", "Other", "Retired on behalf of Acme\nfor 2010", "PASS", ""),
    (VCS, "", "1", WIND, ENERGY, "AMS-I.D. (Version NA)", "", "", "2006",
     "3-17461-17470-VCU-003-APX-IN-1-1-01042006-31122006-0", "10", "VCU", "Asia", "India", "Tamilnadu", "",
     "", "", "FLAG", "missing Retirement Date"),
)  # fmt: skip
CUT_OFF_RETIREMENT = f"{VCS},28 Jul 2023,1,{WIND},{ENERGY},AMS-I.D. (Version NA),,,"
CANCELLATION_ROWS = (
    (VCS, "01-Apr-09", "5", LANDFILL, ENERGY, "ACM0001 (Version NA)", "", "", "2011",
     "2456-104951535-104951634-VCU-025-APX-US-13-5-01012011-31122011-0", "100", "VCU", "North America",
     "United States of America", "PA", "Other", ""),
)  # fmt: skip


def csv_bytes(
    header: Sequence[str], rows: Sequence[Sequence[str]], ending: str = "\n", encoding: str = "utf-8"
) -> bytes:
    """A CSV file's bytes, quoted the way the Verra exports quote."""
    buffer = io.StringIO()
    csv.writer(buffer, lineterminator=ending).writerows([header, *rows])
    return buffer.getvalue().encode(encoding)


def write_snapshot(folder: Path, day: date = DAY) -> Path:
    """One complete drop with the real quirks: a byte-order mark, a line break inside a quoted field and a
    cut-off last record in retirements, and Windows line endings in cancellations."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"VerraIssuances_{day}.csv").write_bytes(csv_bytes(ISSUANCE_HEADER, ISSUANCE_ROWS))
    (folder / f"VerraRetirements_{day}.csv").write_bytes(
        codecs.BOM_UTF8 + csv_bytes(RETIREMENT_HEADER, RETIREMENT_ROWS) + CUT_OFF_RETIREMENT.encode()
    )
    (folder / f"VerraCancelled_{day}.csv").write_bytes(
        csv_bytes(CANCELLATION_HEADER, CANCELLATION_ROWS, "\r\n")
    )
    return folder
