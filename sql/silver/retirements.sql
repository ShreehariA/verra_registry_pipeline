-- One row per bronze row; an undated retirement keeps a NULL date. owner_repairs (made by transform.py) mends
-- mis-encoded owner names, and owner_key groups their spellings.
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
    parse_date(retirement_date) AS retirement_date,
    whole_number(retirement_qty) AS quantity,
    clean_text(coalesce(owner_repairs.repaired, beneficial_owner)) AS beneficial_owner,
    owner_key(coalesce(owner_repairs.repaired, beneficial_owner)) AS owner_key,
    _source_file,
    _source_line
FROM bronze.retirements
LEFT JOIN owner_repairs ON owner_repairs.original = beneficial_owner
ORDER BY _source_line
