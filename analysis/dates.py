"""Dates: the format each file uses, the first and last date, and the retirements with no date.

Behind docs/data-analysis.md, "Dates", and "The files don't end on the same day".
"""

from common import show, snapshot

show(
    "One date as each file writes it",
    "SELECT DISTINCT ON (kind) kind, date_text FROM events WHERE date_text <> '' ORDER BY kind, _source_line",
)
show(
    "How many dates parse with that format, and the first and last date in each file",
    f"""SELECT kind, count(*) AS rows, count(day) AS parsed, count(*) - count(day) AS not_parsed,
           min(day) AS first, max(day) AS last, count(*) FILTER (day > DATE '{snapshot}') AS after_snapshot
       FROM events GROUP BY kind ORDER BY kind""",
)
show(
    "The retirements with no date, and how Verra flags them",
    """SELECT validation_status, validation_issues, count(*) AS rows, sum(retirement_qty::BIGINT) AS credits
       FROM retirements WHERE retirement_date = '' GROUP BY ALL""",
)
