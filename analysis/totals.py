"""docs/data-analysis.md, "Reference numbers": the totals and the 10 largest projects, from the raw text."""

from common import con, show

show(
    "Each file: rows, credits and projects",
    """SELECT kind, count(*) AS rows, sum(qty) AS credits, count(DISTINCT project_id) AS projects
       FROM events GROUP BY kind ORDER BY kind""",
)
con.execute("""
    CREATE VIEW balances AS
    SELECT try_cast(project_id AS BIGINT) AS project_id, any_value(project_name) AS project_name,
        coalesce(sum(qty) FILTER (kind = 'issuance'), 0) AS issued,
        coalesce(sum(qty) FILTER (kind = 'retirement'), 0) AS retired,
        coalesce(sum(qty) FILTER (kind = 'cancellation'), 0) AS cancelled
    FROM events GROUP BY 1
""")
show(
    "All projects together",
    """SELECT count(*) AS projects, sum(issued) AS issued, sum(retired) AS retired,
           sum(cancelled) AS cancelled,
           sum(issued - retired - cancelled) AS available,
           round(100 * available / sum(issued), 1) AS percent_available,
           count(*) FILTER (issued - retired - cancelled < 0) AS projects_below_zero
       FROM balances""",
)
show(
    "The 10 largest projects by credits issued",
    """SELECT project_id, project_name, issued, retired, cancelled, issued - retired - cancelled AS available
       FROM balances ORDER BY issued DESC LIMIT 10""",
)
