"""Format rows as an aligned plain-text table for the terminal."""

from __future__ import annotations

from collections.abc import Collection, Sequence


def format_table(
    columns: Sequence[str],
    rows: Sequence[Sequence[object]],
    right_aligned: Collection[int] = (),
) -> str:
    """Columns padded to equal width. Number columns, and the positions in `right_aligned`, align right."""
    cells = [[_text(value) for value in row] for row in rows]
    widths = [max([len(name), *(len(row[i]) for row in cells)]) for i, name in enumerate(columns)]
    align_right = [i in right_aligned or _all_numbers(rows, i) for i in range(len(columns))]
    lines = [_line(list(columns), widths, align_right), _line(["-" * w for w in widths], widths, align_right)]
    lines.extend(_line(row, widths, align_right) for row in cells)
    return "\n".join(lines)


def _line(cells: Sequence[str], widths: Sequence[int], align_right: Sequence[bool]) -> str:
    padded = (
        cell.rjust(w) if right else cell.ljust(w)
        for cell, w, right in zip(cells, widths, align_right, strict=True)
    )
    return "  ".join(padded).rstrip()


def _text(value: object) -> str:
    """One-line text for a cell; line breaks inside a value are shown as \\n so rows stay aligned."""
    if value is None:
        return "NULL"
    return str(value).replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\r")


def _all_numbers(rows: Sequence[Sequence[object]], position: int) -> bool:
    values = [row[position] for row in rows if row[position] is not None]
    return bool(values) and all(isinstance(v, int | float) and not isinstance(v, bool) for v in values)
