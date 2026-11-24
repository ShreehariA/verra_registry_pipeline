-- Question 2: credits issued, retired and cancelled per vintage, as Verra writes it: '2013' or a range,
-- '2007 - 2008'. The files don't say how a range's credits split across its years, so a chart by year counts a
-- range in vintage_start and says so.
WITH totals AS (
    SELECT
        vintage, vintage_start, vintage_end,
        coalesce(sum(quantity) FILTER (WHERE event_type = 'issuance'), 0)::BIGINT AS issued,
        coalesce(sum(quantity) FILTER (WHERE event_type = 'retirement'), 0)::BIGINT AS retired,
        coalesce(sum(quantity) FILTER (WHERE event_type = 'cancellation'), 0)::BIGINT AS cancelled,
        count(DISTINCT project_id) AS projects
    FROM gold.fct_credit_event
    GROUP BY vintage, vintage_start, vintage_end
)
SELECT
    vintage, vintage_start, vintage_end, projects,
    issued, retired, cancelled, issued - retired - cancelled AS available
FROM totals
ORDER BY vintage_start, vintage_end, vintage
