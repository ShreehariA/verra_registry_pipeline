-- One row per project found in any export. Name, scope, region and state are the same on every row of a project,
-- but methodology and country can change from batch to batch, so each project takes its most common combination
-- of details. Ties go to the alphabetically first, so a rebuild picks the same one.
WITH details AS (
    SELECT project_id, project_name, sectoral_scope, methodology, region, country, state_province
    FROM silver.issuances
    UNION ALL
    SELECT project_id, project_name, sectoral_scope, methodology, region, country, state_province
    FROM silver.retirements
    UNION ALL
    SELECT project_id, project_name, sectoral_scope, methodology, region, country, state_province
    FROM silver.cancellations
),
counted AS (
    SELECT *, count(*) AS row_count FROM details WHERE project_id IS NOT NULL GROUP BY ALL
)
SELECT project_id, project_name, sectoral_scope, methodology, region, country, state_province
FROM counted
QUALIFY row_number() OVER (
    PARTITION BY project_id
    ORDER BY row_count DESC, project_name, sectoral_scope, methodology, region, country, state_province
) = 1
ORDER BY project_id
