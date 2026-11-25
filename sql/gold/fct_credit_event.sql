-- One row per issuance, retirement or cancellation, keyed by event_type and serial_number. A retirement or
-- cancellation shares batch_id and project_id with the issuance its credits came from.
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
