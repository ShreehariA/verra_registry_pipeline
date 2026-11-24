-- Question 1: for each project, the credits issued, retired and cancelled, and what is still available.
WITH totals AS (
    SELECT
        project_id,
        coalesce(sum(quantity) FILTER (WHERE event_type = 'issuance'), 0)::BIGINT AS issued,
        coalesce(sum(quantity) FILTER (WHERE event_type = 'retirement'), 0)::BIGINT AS retired,
        coalesce(sum(quantity) FILTER (WHERE event_type = 'cancellation'), 0)::BIGINT AS cancelled
    FROM gold.fct_credit_event
    GROUP BY project_id
)
SELECT
    p.project_id, p.project_name, p.country, p.sectoral_scope,
    t.issued, t.retired, t.cancelled, t.issued - t.retired - t.cancelled AS available
FROM gold.dim_project AS p
JOIN totals AS t USING (project_id)
ORDER BY p.project_id
