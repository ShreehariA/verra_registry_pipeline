"""docs/data-analysis.md, "Vintages": single years and ranges, and the vintage against the serial number."""

from common import con, show

con.execute(r"""
    CREATE VIEW vintages AS
    SELECT kind, vintage, qty, serial_number,
        regexp_extract(vintage, '^(\d{4})', 1)::INT AS first_year,
        coalesce(nullif(regexp_extract(vintage, ' - (\d{4})$', 1), ''),
            regexp_extract(vintage, '^(\d{4})', 1))::INT AS last_year,
        try_strptime(regexp_extract(serial_number, '-(\d{8})[-_]\d{8}-\d+$', 1), '%d%m%Y')::DATE
            AS period_start,
        try_strptime(regexp_extract(serial_number, '-\d{8}[-_](\d{8})-\d+$', 1), '%d%m%Y')::DATE
            AS period_end,
        year(period_start) = first_year AND year(period_end) = last_year AS same_years
    FROM events
""")
show(
    "Issued credits by the number of years their vintage spans",
    """SELECT last_year - first_year + 1 AS years, count(*) AS batches, sum(qty) AS credits
       FROM vintages WHERE kind = 'issuance' GROUP BY ALL ORDER BY ALL""",
)
show(
    "The share of issued credits whose vintage is a range",
    """SELECT sum(qty) FILTER (last_year > first_year) AS in_ranges, sum(qty) AS issued,
           round(100 * in_ranges / issued, 1) AS percent
       FROM vintages WHERE kind = 'issuance'""",
)
show(
    "Does the vintage name the same years as the monitoring period in the serial?",
    """SELECT kind, count(*) FILTER (same_years) AS same, count(*) FILTER (NOT same_years) AS different
       FROM vintages GROUP BY kind ORDER BY kind""",
)
show(
    "The rows where they differ",
    "SELECT kind, vintage, period_start, period_end, serial_number FROM vintages WHERE NOT same_years",
)
