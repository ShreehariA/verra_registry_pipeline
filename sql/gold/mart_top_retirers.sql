-- Question 3: who retires the most, and what. One row per owner and project. owner_rank ranks the named owners by
-- all the credits they retired; 'unspecified' (blank or placeholder owners) has no rank but stays in the totals.
WITH by_project AS (
    SELECT
        owner_key, project_id,
        sum(quantity)::BIGINT AS credits,
        count(*) AS retirements,
        string_agg(DISTINCT vintage, ', ' ORDER BY vintage) AS vintages,
        min(event_date) AS first_retired,
        max(event_date) AS last_retired
    FROM gold.fct_credit_event
    WHERE event_type = 'retirement'
    GROUP BY owner_key, project_id
),
by_owner AS (
    SELECT
        owner_key,
        sum(credits)::BIGINT AS owner_credits,
        CASE WHEN owner_key <> 'unspecified' THEN rank() OVER (
            PARTITION BY owner_key = 'unspecified' ORDER BY sum(credits) DESC
        ) END AS owner_rank
    FROM by_project
    GROUP BY owner_key
)
SELECT
    o.owner_rank, b.owner_key, d.owner_name, o.owner_credits,
    b.project_id, p.project_name, p.sectoral_scope, p.country,
    b.credits, b.retirements, b.vintages, b.first_retired, b.last_retired
FROM by_project AS b
JOIN by_owner AS o USING (owner_key)
JOIN gold.dim_beneficial_owner AS d USING (owner_key)
JOIN gold.dim_project AS p USING (project_id)
ORDER BY o.owner_rank NULLS LAST, b.owner_key, b.credits DESC, b.project_id
