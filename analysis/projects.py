"""Projects and places: do the files agree on projects, and can the project details and places be trusted?

Behind docs/data-analysis.md, "Projects and places".
"""

from common import con, show

show(
    "Projects in each file, and how many of them are also in issuances",
    """SELECT kind, count(DISTINCT project_id) AS projects,
           count(DISTINCT project_id) FILTER (project_id IN (SELECT project_id FROM issuances)) AS also_issued
       FROM events GROUP BY kind ORDER BY kind""",
)
for column in ("project_name", "sectoral_scope", "methodology", "region", "country", "state_province"):
    [(projects,)] = con.sql(
        f"SELECT count(*) FROM (SELECT project_id FROM events GROUP BY 1 HAVING count(DISTINCT {column}) > 1)"
    ).fetchall()
    print(f"- {column}: {projects} project(s) with more than one value across the files")
show(
    "The project with several countries",
    """SELECT project_id, country, count(*) AS rows FROM events
       WHERE project_id IN (SELECT project_id FROM events GROUP BY 1 HAVING count(DISTINCT country) > 1)
       GROUP BY ALL ORDER BY ALL""",
)
show(
    "Countries filed under more than one region (a blank region counts as one)",
    """SELECT country, string_agg(DISTINCT coalesce(nullif(region, ''), '(blank)'), ', '
               ORDER BY coalesce(nullif(region, ''), '(blank)')) AS regions,
           count(*) AS rows
       FROM events GROUP BY country HAVING count(DISTINCT region) > 1 ORDER BY country""",
)
show("Rows with a blank region", "SELECT count(*) AS rows FROM events WHERE region = ''")
show(
    "The 2-letter country code inside the serial number, against the country column",
    r"""SELECT country,
           regexp_extract(serial_number, '-([A-Za-z]{2})-(?:\d+-)?\d+-\d{8}[-_]\d{8}-\d+$', 1) AS code,
           count(*) AS rows
       FROM events WHERE country IN ('Korea (Republic of)', 'Turkey') GROUP BY ALL ORDER BY ALL""",
)
show(
    "One state, two spellings",
    """SELECT state_province, count(DISTINCT project_id) AS projects FROM events
       WHERE state_province ILIKE 'tamil%' GROUP BY 1 ORDER BY 1""",
)
