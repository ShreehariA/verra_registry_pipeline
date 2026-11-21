import hashlib
from pathlib import Path

import pytest

from tests.verra_files import csv_line
from verra_pipeline.errors import UnreadableFileError
from verra_pipeline.ingest.csv_reader import CsvFileReader, ParsedCsv

HEADER = ("Project ID", "Project Name", "Retirement QTY")


def read_bytes(tmp_path: Path, content: bytes) -> ParsedCsv:
    path = tmp_path / "VerraRetirements_2030-01-15.csv"
    path.write_bytes(content)
    return CsvFileReader().read(path)


def read_text(tmp_path: Path, text: str) -> ParsedCsv:
    return read_bytes(tmp_path, text.encode("utf-8"))


def test_reads_every_record_with_the_line_it_starts_on(tmp_path: Path) -> None:
    parsed = read_text(tmp_path, f"{csv_line(HEADER)}\n1,Wind,100\n2,Hydro,250\n")

    assert parsed.header == HEADER
    assert [(r.line_number, r.values) for r in parsed.records] == [
        (2, ("1", "Wind", "100")),
        (3, ("2", "Hydro", "250")),
    ]


def test_quoted_commas_and_line_breaks_stay_inside_one_field(tmp_path: Path) -> None:
    text = f'{csv_line(HEADER)}\n1,"Wind, Phase 2\nTamil Nadu",100\n2,Hydro,250\n'

    parsed = read_text(tmp_path, text)

    assert parsed.records[0].values[1] == "Wind, Phase 2\nTamil Nadu"
    assert parsed.records[1].line_number == 4, "the record after a two-line record starts on line 4"


def test_removes_a_utf8_byte_order_mark_and_records_it(tmp_path: Path) -> None:
    parsed = read_bytes(tmp_path, b"\xef\xbb\xbf" + f"{csv_line(HEADER)}\n1,Wind,100\n".encode())

    assert parsed.header[0] == "Project ID"
    assert parsed.profile.has_bom
    assert parsed.profile.encoding == "utf-8-sig"


def test_reads_crlf_files_and_records_the_line_endings(tmp_path: Path) -> None:
    parsed = read_text(tmp_path, f"{csv_line(HEADER)}\r\n1,Wind,100\r\n")

    assert parsed.records[0].values == ("1", "Wind", "100")
    assert parsed.profile.line_endings == "CRLF"


def test_quarantines_a_record_with_the_wrong_number_of_fields(tmp_path: Path) -> None:
    parsed = read_text(tmp_path, f"{csv_line(HEADER)}\n1,Wind,100\n2,Hydro\n3,Solar,10\n")

    assert len(parsed.records) == 2
    rejected = parsed.rejected[0]
    assert (rejected.line_number, rejected.reason, rejected.raw_text) == (
        3,
        "expected 3 fields, found 2",
        "2,Hydro\n",
    )


def test_explains_that_a_last_record_without_a_newline_was_cut_off(tmp_path: Path) -> None:
    parsed = read_text(tmp_path, f"{csv_line(HEADER)}\n1,Wind,100\n2,Hy")

    assert not parsed.profile.ends_with_newline
    assert "probably cut off" in parsed.rejected[0].reason


def test_skips_blank_lines_and_counts_them(tmp_path: Path) -> None:
    parsed = read_text(tmp_path, f"{csv_line(HEADER)}\n1,Wind,100\n\n2,Hydro,250\n")

    assert len(parsed.records) == 2
    assert parsed.blank_lines == 1


def test_reads_windows_1252_when_the_bytes_are_not_utf8(tmp_path: Path) -> None:
    parsed = read_bytes(tmp_path, f"{csv_line(HEADER)}\n1,Cosm".encode() + b"\xe9ticos,5\n")

    assert parsed.records[0].values[1] == "Cosméticos"
    assert parsed.profile.encoding == "cp1252"


def test_records_the_size_and_checksum_of_the_raw_bytes(tmp_path: Path) -> None:
    content = f"{csv_line(HEADER)}\n1,Wind,100\n".encode()

    profile = read_bytes(tmp_path, content).profile

    assert profile.size_bytes == len(content)
    assert profile.sha256 == hashlib.sha256(content).hexdigest()


def test_counts_data_lines_and_quarantined_lines(tmp_path: Path) -> None:
    parsed = read_text(tmp_path, f'{csv_line(HEADER)}\n1,Wind,100\n2,"Hydro\nstill open\n')

    assert parsed.data_lines == 3
    assert parsed.rejected_lines == 2


@pytest.mark.parametrize("content", [b"", b"\xef\xbb\xbf", b"\n1,Wind,100\n"])
def test_a_file_without_a_header_is_unreadable(tmp_path: Path, content: bytes) -> None:
    with pytest.raises(UnreadableFileError, match="no header row"):
        read_bytes(tmp_path, content)
