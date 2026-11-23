import dataclasses
import hashlib
from collections.abc import Callable
from datetime import date
from typing import Any

import duckdb
import pytest

from tests.verra_files import (
    CUT_OFF_RETIREMENT,
    DAY,
    ISSUANCE_HEADER,
    ISSUANCE_ROWS,
    RETIREMENT_HEADER,
    RETIREMENT_ROWS,
    csv_bytes,
    write_snapshot,
)
from verra_pipeline import PipelineError
from verra_pipeline.config import Config
from verra_pipeline.ingest import find_snapshot, ingest
from verra_pipeline.lake import partition


def rows(config: Config, table: str) -> list[dict[str, Any]]:
    relation = duckdb.read_parquet(str(partition(config.lake, "bronze", table, DAY)))
    return [dict(zip(relation.columns, row, strict=True)) for row in relation.fetchall()]


def findings(manifest: dict[str, Any], table: str) -> list[str]:
    return next(file["findings"] for file in manifest["files"] if file["table"] == table)


def rewrite(config: Config, prefix: str, content: bytes) -> None:
    (config.landing / f"{prefix}_{DAY}.csv").write_bytes(content)


def without(header: tuple[str, ...], rows: tuple[tuple[str, ...], ...], name: str) -> bytes:
    keep = [i for i, column in enumerate(header) if column != name]
    return csv_bytes([header[i] for i in keep], [[row[i] for i in keep] for row in rows])


def test_loads_every_file_and_reports_its_quirks(config: Config) -> None:
    manifest = ingest(config)

    assert manifest["snapshot_date"] == "2030-01-15"
    assert [
        (f["table"], f["rows_read"], f["rows_loaded"], f["rows_quarantined"]) for f in manifest["files"]
    ] == [
        ("issuances", 2, 2, 0),
        ("retirements", 3, 2, 1),
        ("cancellations", 1, 1, 0),
    ]
    assert findings(manifest, "retirements")[:2] == [
        "starts with a byte-order mark, which was removed",
        "does not end with a newline, so its last record may be cut off",
    ]
    assert findings(manifest, "cancellations") == ["uses Windows (CRLF) line endings"]


def test_keeps_values_as_delivered_and_where_each_row_came_from(config: Config) -> None:
    ingest(config)
    retirements = config.landing / f"VerraRetirements_{DAY}.csv"

    first, undated = rows(config, "retirements")

    assert first["retirement_reason_details"] == "Retired on behalf of Acme\nfor 2010"
    assert undated["retirement_date"] == "", "bronze keeps a blank as delivered; silver decides what it means"
    assert (first["_source_line"], undated["_source_line"]) == (2, 4), "the first record spans lines 2 and 3"
    assert (first["_snapshot_date"], first["_source_file"]) == (DAY, retirements.name)
    assert first["_file_sha256"] == hashlib.sha256(retirements.read_bytes()).hexdigest()


def test_quarantines_the_cut_off_record_with_its_exact_text(config: Config) -> None:
    ingest(config)

    [record] = rows(config, "rejected_records")

    assert (record["target_table"], record["_source_line"], record["line_count"]) == ("retirements", 5, 1)
    assert record["reason"] == (
        "expected 20 fields, found 9; the file ends inside this record, so it was probably cut off"
    )
    assert record["raw_text"] == CUT_OFF_RETIREMENT


def test_matches_headers_by_name_in_any_order_and_through_aliases(config: Config) -> None:
    renamed = ["Quantity Retired" if name == "Retirement QTY" else name for name in RETIREMENT_HEADER]
    rewrite(config, "VerraRetirements", csv_bytes(renamed[::-1], [row[::-1] for row in RETIREMENT_ROWS]))
    issuances, retirements, cancellations = config.sources
    with_alias = dataclasses.replace(retirements, aliases={"quantity_retired": "retirement_qty"})

    ingest(dataclasses.replace(config, sources=(issuances, with_alias, cancellations)))

    assert [row["retirement_qty"] for row in rows(config, "retirements")] == ["100", "10"]


def test_loads_a_missing_optional_column_empty(config: Config) -> None:
    rewrite(config, "VerraRetirements", without(RETIREMENT_HEADER, RETIREMENT_ROWS, "Region"))

    manifest = ingest(config)

    assert {row["region"] for row in rows(config, "retirements")} == {None}
    assert "lacks optional columns, loaded empty: region" in findings(manifest, "retirements")


def test_reads_windows_1252_when_a_file_is_not_utf8(config: Config) -> None:
    accented = (*ISSUANCE_ROWS[0][:3], "Café wind", *ISSUANCE_ROWS[0][4:])
    rewrite(config, "VerraIssuances", csv_bytes(ISSUANCE_HEADER, [accented], encoding="cp1252"))

    manifest = ingest(config)

    assert rows(config, "issuances")[0]["project_name"] == "Café wind"
    assert "is not valid UTF-8 and was read as Windows-1252; check accented names" in findings(
        manifest, "issuances"
    )


def test_skips_blank_lines_and_says_so(config: Config) -> None:
    rewrite(config, "VerraIssuances", csv_bytes(ISSUANCE_HEADER, ISSUANCE_ROWS) + b"\n")

    manifest = ingest(config)

    assert findings(manifest, "issuances") == ["has 1 blank line(s), skipped"]
    assert len(rows(config, "issuances")) == 2


BROKEN: dict[str, tuple[Callable[[Config], None], str]] = {
    "missing file": (lambda c: (c.landing / f"VerraCancelled_{DAY}.csv").unlink(), "no date has all 3 files"),
    "empty file": (lambda c: rewrite(c, "VerraIssuances", b""), "has no header row"),
    "missing required column": (
        lambda c: rewrite(c, "VerraIssuances", without(ISSUANCE_HEADER, ISSUANCE_ROWS, "Units")),
        "required columns are missing: units",
    ),
    "repeated header": (
        lambda c: rewrite(
            c,
            "VerraIssuances",
            csv_bytes((*ISSUANCE_HEADER, "Units"), [(*row, "1") for row in ISSUANCE_ROWS]),
        ),
        "these headers appear more than once: units",
    ),
    "no rows": (
        lambda c: rewrite(c, "VerraIssuances", csv_bytes(ISSUANCE_HEADER, [])),
        "has a header but no readable rows",
    ),
    "one broken quote swallowing the rest": (
        lambda c: rewrite(
            c,
            "VerraRetirements",
            csv_bytes(RETIREMENT_HEADER, RETIREMENT_ROWS) + b'VCS,"never closed\n' + b"more text\n" * 10,
        ),
        r"11 of 14 lines \(78.6%\) could not be read; at most 50% is allowed",
    ),
}


@pytest.mark.parametrize("case", list(BROKEN))
def test_refuses_input_it_cannot_trust_and_writes_nothing(config: Config, case: str) -> None:
    break_it, message = BROKEN[case]
    break_it(config)

    with pytest.raises(PipelineError, match=message):
        ingest(config)
    assert not config.lake.exists()


def test_a_rerun_gives_byte_identical_files(config: Config) -> None:
    ingest(config)
    first = {path: path.read_bytes() for path in config.lake.rglob("*") if path.is_file()}

    ingest(config)

    assert {path: path.read_bytes() for path in config.lake.rglob("*") if path.is_file()} == first


def test_picks_the_newest_complete_snapshot_and_ignores_other_files(config: Config) -> None:
    write_snapshot(config.landing, date(2030, 1, 14))
    for name in ("VerraIssuances_2030-01-16.csv", "VerraIssuances_2030-13-45.csv", "README.txt"):
        (config.landing / name).write_bytes(b"not a drop")

    assert find_snapshot(config)[0] == DAY
    with pytest.raises(
        PipelineError, match=r"2030-01-16 is missing VerraRetirements_2030-01-16\.csv, VerraCancel"
    ):
        find_snapshot(config, date(2030, 1, 16))
    with pytest.raises(PipelineError, match="no files dated 2030-01-17"):
        find_snapshot(config, date(2030, 1, 17))
