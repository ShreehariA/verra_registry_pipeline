"""Decide when a file has too many unreadable lines to be trusted at all."""

from __future__ import annotations

from dataclasses import dataclass

from verra_pipeline.errors import RejectBudgetExceededError
from verra_pipeline.ingest.csv_reader import ParsedCsv


@dataclass(frozen=True)
class RejectBudget:
    """A few bad lines go to quarantine; more than `max_share` of a file stops the run.

    The share is counted in lines, not records, because one broken quote can
    swallow thousands of lines into a single bad record. Counting records would
    hide that; counting lines exposes it.
    """

    max_share: float = 0.01

    def check(self, parsed: ParsedCsv) -> None:
        if not parsed.data_lines:
            return
        share = parsed.rejected_lines / parsed.data_lines
        if share > self.max_share:
            raise RejectBudgetExceededError(
                f"{parsed.profile.file_name}: {parsed.rejected_lines:,} of {parsed.data_lines:,} lines "
                f"({_percent(share)}) could not be read; at most {_percent(self.max_share)} is allowed"
            )


def _percent(share: float) -> str:
    """Two significant digits, so a tiny share reads 0.0043% instead of rounding to 0.0%."""
    return f"{share * 100:.2g}%"
