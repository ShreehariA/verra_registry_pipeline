-- The fact table: one row per issuance, retirement or cancellation, keyed by event_type and serial_number. Every
-- credit total is a sum of quantity. A retirement or cancellation has the same batch_id and project_id as the
-- issuance its credits came from, and its serial range lies inside that issuance's range.
SELECT
    'issuance' AS event_type, serial_number, batch_id, serial_first, serial_last, project_id,
    NULL::VARCHAR AS owner_key, issuance_date AS event_date, vintage, vintage_start, vintage_end, quantity,
    _source_file, _source_line
FROM silver.issuances
UNION ALL
SELECT
    'retirement', serial_number, batch_id, serial_first, serial_last, project_id,
    owner_key, retirement_date, vintage, vintage_start, vintage_end, quantity,
    _source_file, _source_line
FROM silver.retirements
UNION ALL
SELECT
    'cancellation', serial_number, batch_id, serial_first, serial_last, project_id,
    NULL, cancellation_date, vintage, vintage_start, vintage_end, quantity,
    _source_file, _source_line
FROM silver.cancellations
ORDER BY event_type, serial_number, _source_line
