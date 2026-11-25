"""docs/data-analysis.md, "Reasons and multi-value fields": why credits were retired or cancelled."""

from common import show

show(
    "Retirement reasons, by credits",
    """SELECT retirement_reason, count(*) AS rows, sum(retirement_qty::BIGINT) AS credits
       FROM retirements GROUP BY 1 ORDER BY credits DESC LIMIT 8""",
)
show(
    "Cancellation reasons, and whether their details say more",
    """SELECT cancellation_reason, count(*) AS rows, count(*) FILTER (cancellation_reason_details <> '')
           AS with_details
       FROM cancellations GROUP BY 1 ORDER BY rows DESC""",
)
show(
    "Commas separate several values, but a single value can hold commas too",
    """SELECT DISTINCT sectoral_scope FROM events
       WHERE sectoral_scope LIKE '%,%' ORDER BY 1""",
)
