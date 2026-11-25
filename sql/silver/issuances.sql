-- One row per bronze row. A value that can't be read becomes NULL, which checks.sql counts: no row is dropped.
SELECT
    whole_number(project_id) AS project_id,
    clean_text(project_name) AS project_name,
    clean_text(sectoral_scope) AS sectoral_scope,
    clean_text(methodology) AS methodology,
    clean_text(region) AS region,
    clean_text(country) AS country,
    clean_text(state_province) AS state_province,
    clean_text(vintage) AS vintage,
    vintage_start(vintage) AS vintage_start,
    vintage_end(vintage) AS vintage_end,
    trim(serial_number) AS serial_number,
    serial_part(serial_number, 1) AS batch_id,
    serial_part(serial_number, 2) AS serial_first,
    serial_part(serial_number, 3) AS serial_last,
    parse_date(issuance_date) AS issuance_date,
    whole_number(units) AS quantity,
    _source_file,
    _source_line
FROM bronze.issuances
ORDER BY _source_line
