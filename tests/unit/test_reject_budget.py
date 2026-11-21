import pytest

from verra_pipeline.errors import RejectBudgetExceededError
from verra_pipeline.ingest.csv_reader import FileProfile, ParsedCsv, RejectedRecord
from verra_pipeline.ingest.reject_budget import RejectBudget

PROFILE = FileProfile("VerraRetirements_2030-01-15.csv", 0, "", "utf-8", False, "LF", True)


def parsed_with(data_lines: int, rejected_line_counts: list[int]) -> ParsedCsv:
    rejected = tuple(RejectedRecord(2, count, "bad", "") for count in rejected_line_counts)
    return ParsedCsv(PROFILE, ("a",), (), rejected, blank_lines=0, data_lines=data_lines)


def test_a_tiny_share_is_shown_precisely_not_rounded_to_zero() -> None:
    with pytest.raises(RejectBudgetExceededError, match=r"1 of 23,283 lines \(0.0043%\)"):
        RejectBudget(max_share=0.00001).check(parsed_with(data_lines=23_283, rejected_line_counts=[1]))


def test_a_few_bad_lines_are_allowed() -> None:
    RejectBudget(max_share=0.01).check(parsed_with(data_lines=23_283, rejected_line_counts=[1]))


def test_too_many_bad_lines_stop_the_run() -> None:
    expected = r"3 of 100 lines \(3%\) could not be read; at most 1% is allowed"

    with pytest.raises(RejectBudgetExceededError, match=expected):
        RejectBudget(max_share=0.01).check(parsed_with(data_lines=100, rejected_line_counts=[1, 1, 1]))


def test_counts_lines_so_one_broken_quote_swallowing_a_file_is_caught() -> None:
    one_record_spanning_most_of_the_file = [900]

    with pytest.raises(RejectBudgetExceededError):
        RejectBudget(max_share=0.01).check(parsed_with(1_000, one_record_spanning_most_of_the_file))


def test_a_file_without_data_lines_is_left_to_other_checks() -> None:
    RejectBudget().check(parsed_with(data_lines=0, rejected_line_counts=[]))
