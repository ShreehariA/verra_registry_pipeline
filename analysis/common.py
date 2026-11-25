"""What every analysis script shares: one snapshot's three files, loaded as delivered, and a printer.

The pipeline's own reader loads them as text, with each row's file and line. Nothing is cleaned or written.
"""

from pathlib import Path

import duckdb

from verra_pipeline.config import load
from verra_pipeline.ingest import find_snapshot, ingest

config = load(Path(__file__).resolve().parent.parent / "pipeline.toml")  # works from any folder
snapshot, files, _ = find_snapshot(config)  # the newest date with all three files in data/landing
con = duckdb.connect()
ingest(con, config, snapshot)
con.execute("SET search_path = 'bronze'")  # so a query says `retirements`, as the file is named

# The three files as one table of events. Dates and quantities are read here, with each file's formats; one
# that doesn't parse stays empty, so it can be counted. A quantity is digits only: 12.5 isn't rounded to 13.
con.execute(r"""
    CREATE MACRO digits(text) AS try_cast(regexp_extract(text, '^\s*(\d+)\s*$', 1) AS BIGINT);
    CREATE VIEW events AS
    SELECT 'issuance' AS kind, issuance_date AS date_text,
        try_strptime(issuance_date, '%d %b %Y')::DATE AS day, digits(units) AS qty,
        project_id, project_name, vintage, serial_number, region, country,
        state_province, sectoral_scope, methodology, NULL AS owner, _source_line
    FROM issuances
    UNION ALL
    SELECT 'retirement', retirement_date, try_strptime(retirement_date, '%d %b %Y')::DATE,
        digits(retirement_qty), project_id, project_name, vintage, serial_number, region, country,
        state_province, sectoral_scope, methodology, beneficial_owner, _source_line
    FROM retirements
    UNION ALL
    SELECT 'cancellation', cancellation_date, try_strptime(cancellation_date, '%d-%b-%y')::DATE,
        digits(cancellation_qty), project_id, project_name, vintage, serial_number, region, country,
        state_province, sectoral_scope, methodology, NULL, _source_line
    FROM cancellations
""")


def show(question: str, sql: str, rows: int = 40) -> None:
    """Print the question, then DuckDB's answer as a table."""
    print(f"\n## {question}")
    con.sql(sql).show(max_rows=rows, max_width=200)


print(f"# Snapshot {snapshot}, read from {config.landing.parent.name}/{config.landing.name}/ as delivered")
