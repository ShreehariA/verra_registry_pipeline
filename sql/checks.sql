-- The quality gate: one row per check. failing_rows counts the rows that break the rule and failing_credits the
-- credits involved; zero passes. A failed 'error' means a number would be wrong, so the build stops before anything
-- is written. A 'warning' is a fact about the data worth knowing: the build report and the dashboard show it.
WITH events AS (
    SELECT * FROM gold.fct_credit_event
),
used AS (
    SELECT * FROM events WHERE event_type <> 'issuance'
),
-- each retirement or cancellation, with the issued batch its credits came from
traced AS (
    SELECT u.*, i.event_date AS issued_on, i.serial_number AS issued_serial, i.quantity AS issued_quantity
    FROM used AS u
    JOIN events AS i
        ON i.event_type = 'issuance' AND i.batch_id = u.batch_id AND i.project_id = u.project_id
        AND u.serial_first >= i.serial_first AND u.serial_last <= i.serial_last
),
silver_totals AS (
    SELECT 'issuance' AS event_type, count(*) AS row_count, sum(quantity) AS credits FROM silver.issuances
    UNION ALL SELECT 'retirement', count(*), sum(quantity) FROM silver.retirements
    UNION ALL SELECT 'cancellation', count(*), sum(quantity) FROM silver.cancellations
),
fact_totals AS (
    SELECT event_type, count(*) AS row_count, sum(quantity) AS credits FROM events GROUP BY event_type
),
-- issued, retired and cancelled credits as each gold table adds them up
added_up AS (
    SELECT 'fct_credit_event' AS source, event_type, credits FROM fact_totals
    UNION ALL SELECT 'mart_project_balance', 'issuance', sum(issued) FROM gold.mart_project_balance
    UNION ALL SELECT 'mart_project_balance', 'retirement', sum(retired) FROM gold.mart_project_balance
    UNION ALL SELECT 'mart_project_balance', 'cancellation', sum(cancelled) FROM gold.mart_project_balance
    UNION ALL SELECT 'mart_vintage_activity', 'issuance', sum(issued) FROM gold.mart_vintage_activity
    UNION ALL SELECT 'mart_vintage_activity', 'retirement', sum(retired) FROM gold.mart_vintage_activity
    UNION ALL SELECT 'mart_vintage_activity', 'cancellation', sum(cancelled) FROM gold.mart_vintage_activity
    UNION ALL SELECT 'mart_top_retirers', 'retirement', sum(credits) FROM gold.mart_top_retirers
),
checks AS (
    SELECT 'error' AS severity, 'silver has exactly one row per bronze row' AS check_name,
        abs((SELECT count(*) FROM bronze.issuances) - (SELECT count(*) FROM silver.issuances))
        + abs((SELECT count(*) FROM bronze.retirements) - (SELECT count(*) FROM silver.retirements))
        + abs((SELECT count(*) FROM bronze.cancellations) - (SELECT count(*) FROM silver.cancellations))
        AS failing_rows,
        NULL AS failing_credits
    UNION ALL
    SELECT 'error', 'every quantity is a whole number above zero', count(*), NULL
    FROM events WHERE quantity IS NULL OR quantity <= 0
    UNION ALL
    SELECT 'error', 'every row has a project id', count(*), sum(quantity)
    FROM events WHERE project_id IS NULL
    UNION ALL
    SELECT 'error', 'no serial number appears twice in one export',
        count(*) - count(DISTINCT (event_type, serial_number)), NULL
    FROM events WHERE serial_number <> ''  -- a blank one is reported below, as unreadable
    UNION ALL
    SELECT 'error', 'the fact table has the same rows and credits as silver',
        sum(abs(s.row_count - coalesce(f.row_count, 0))),
        sum(abs(coalesce(s.credits, 0) - coalesce(f.credits, 0)))
    FROM silver_totals AS s
    LEFT JOIN fact_totals AS f USING (event_type)
    UNION ALL
    -- the marts join the dimensions, so this also proves no event points at a missing project or owner
    SELECT 'error', 'the marts add up to the fact table', NULL,
        sum(abs(coalesce(a.credits, 0) - coalesce(f.credits, 0)))
    FROM added_up AS a
    LEFT JOIN fact_totals AS f USING (event_type)
    WHERE a.source <> 'fct_credit_event'
    UNION ALL
    SELECT 'warning', 'records quarantined: unreadable lines in the raw files', count(*), NULL
    FROM bronze.rejected_records
    UNION ALL
    SELECT 'warning', 'events with no readable date', count(*), sum(quantity)
    FROM events WHERE event_date IS NULL
    UNION ALL
    SELECT 'warning', 'dates before 2008 or after the snapshot date', count(*), sum(quantity)
    FROM events WHERE event_date < DATE '2008-01-01' OR event_date > getvariable('snapshot_date')
    UNION ALL
    SELECT 'warning', 'serial numbers that could not be read', count(*), sum(quantity)
    FROM events WHERE batch_id IS NULL OR serial_first IS NULL OR serial_last IS NULL
    UNION ALL
    SELECT 'warning', 'vintages that could not be read', count(*), sum(quantity)
    FROM events WHERE vintage_start IS NULL OR vintage_end IS NULL
    UNION ALL
    SELECT 'warning', 'quantity differs from the size of the serial range', count(*), sum(quantity)
    FROM events WHERE quantity <> serial_last - serial_first + 1
    UNION ALL
    SELECT 'warning', 'retired or cancelled credits outside every issued batch', count(*), sum(quantity)
    FROM used AS u
    WHERE NOT EXISTS (
        SELECT 1 FROM traced AS t WHERE t.event_type = u.event_type AND t._source_line = u._source_line
    )
    UNION ALL
    SELECT 'warning', 'retired or cancelled before the batch was issued', count(*), sum(quantity)
    FROM traced WHERE event_date < issued_on
    UNION ALL
    SELECT 'warning', 'credits retired or cancelled twice (overlapping serial ranges)', count(*), NULL
    FROM used AS a
    JOIN used AS b
        ON a.batch_id = b.batch_id AND a.project_id = b.project_id
        AND a.serial_first <= b.serial_last AND b.serial_first <= a.serial_last
        AND (a.event_type, a._source_line) < (b.event_type, b._source_line)
    UNION ALL
    SELECT 'warning', 'batches with more retired and cancelled than issued', count(*), sum(used - issued_quantity)
    FROM (
        SELECT issued_serial, any_value(issued_quantity) AS issued_quantity, sum(quantity) AS used
        FROM traced GROUP BY issued_serial
    )
    WHERE used > issued_quantity
    UNION ALL
    SELECT 'warning', 'projects with a negative available balance', count(*), -sum(available)
    FROM gold.mart_project_balance WHERE available < 0
    UNION ALL
    SELECT 'warning', 'projects with retirements or cancellations but no issuance', count(*), sum(retired + cancelled)
    FROM gold.mart_project_balance WHERE issued = 0
    UNION ALL
    SELECT 'warning', 'retired credits with no named owner', count(*), sum(quantity)
    FROM events WHERE event_type = 'retirement' AND owner_key = 'unspecified'
)
SELECT
    severity,
    check_name,
    coalesce(failing_rows, 0)::BIGINT AS failing_rows,
    coalesce(failing_credits, 0)::BIGINT AS failing_credits,
    coalesce(failing_rows, 0) = 0 AND coalesce(failing_credits, 0) = 0 AS passed
FROM checks
ORDER BY severity, check_name
