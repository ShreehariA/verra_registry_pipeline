"""Serial numbers and batches: what a serial number holds, and how each retirement and cancellation
traces back to the batch it was issued in.

Behind docs/data-analysis.md, "Serial numbers and batches", and the retirements dated before their batch was
issued ("Dates").
"""

from common import con, show

# A serial starts with the batch number and the range's first and last serial, in both serial families:
# 10026-172542403-172547402-VCS-VCU-263-VER-... (newer) and 1247-54685576-54747845-VCU-008-CDC-IN-... (older).
con.execute(r"""
    CREATE TABLE ranges AS
    SELECT *,
        regexp_extract(serial_number, '^(\d+)-', 1)::BIGINT AS batch,
        regexp_extract(serial_number, '^\d+-(\d+)-', 1)::BIGINT AS first_serial,
        regexp_extract(serial_number, '^\d+-\d+-(\d+)-', 1)::BIGINT AS last_serial,
        CASE WHEN serial_number LIKE '%-VCS-VCU-%' THEN 'newer' ELSE 'older' END AS family,
        regexp_extract(serial_number, '-VCU-\d+-([A-Z0-9]+)-', 1) AS old_registry
    FROM events
""")
show(
    "The two serial families, and how many parts each has",
    """SELECT kind, family, len(string_split(serial_number, '-')) AS parts, count(*) AS rows
       FROM ranges GROUP BY ALL ORDER BY ALL""",
)
show(
    "Does the quantity equal the size of the serial range on every row?",
    """SELECT kind, count(*) FILTER (qty = last_serial - first_serial + 1) AS equal,
           count(*) FILTER (qty <> last_serial - first_serial + 1) AS different
       FROM ranges GROUP BY kind ORDER BY kind""",
)
show(
    "The trap: matching on the serial range alone finds more issuances than there are retirements",
    """SELECT r.kind, count(DISTINCT r._source_line) AS events, count(*) AS matches
       FROM ranges AS r JOIN ranges AS i
           ON i.kind = 'issuance' AND r.first_serial >= i.first_serial AND r.last_serial <= i.last_serial
       WHERE r.kind <> 'issuance' GROUP BY r.kind ORDER BY r.kind""",
)

# The match that holds: the same batch number and project, and the range inside the issued range
con.execute("""
    CREATE TABLE traced AS
    SELECT r.*, i.day AS issued_on, i.vintage AS issued_vintage, i.qty AS issued_qty,
        i._source_line AS issued_line
    FROM ranges AS r LEFT JOIN ranges AS i
        ON i.kind = 'issuance' AND i.batch = r.batch AND i.project_id = r.project_id
        AND r.first_serial >= i.first_serial AND r.last_serial <= i.last_serial
    WHERE r.kind <> 'issuance'
""")
show(
    "Each retirement and cancellation inside exactly one issued batch?",
    """SELECT kind, count(*) AS matches, count(DISTINCT _source_line) AS events,
           count(issued_line) AS in_a_batch,
           count(*) - count(issued_line) AS in_no_batch
       FROM traced GROUP BY kind ORDER BY kind""",
)
show(
    "Does each event have the vintage of its batch?",
    """SELECT kind, count(*) FILTER (vintage = issued_vintage) AS same,
           count(*) FILTER (vintage <> issued_vintage) AS different
       FROM traced GROUP BY kind ORDER BY kind""",
)
show(
    "Events dated before their batch was issued",
    """SELECT kind, count(*) AS rows, sum(qty) AS credits, max(issued_on - day) AS most_days_before,
           string_agg(DISTINCT old_registry, ', ' ORDER BY old_registry) AS old_registries
       FROM traced WHERE day < issued_on GROUP BY kind""",
)
show(
    "The same credits retired or cancelled twice: overlapping ranges in one batch",
    """SELECT count(*) AS overlapping_pairs FROM ranges AS a JOIN ranges AS b
           ON a.batch = b.batch AND a.project_id = b.project_id
           AND a.first_serial <= b.last_serial AND b.first_serial <= a.last_serial
           AND (a.kind, a._source_line) < (b.kind, b._source_line)
       WHERE a.kind <> 'issuance' AND b.kind <> 'issuance'""",
)
show(
    "Batches with more retired and cancelled than issued",
    """SELECT count(*) AS batches_used, count(*) FILTER (used > issued) AS used_more_than_issued,
           count(*) FILTER (used = issued) AS fully_used
       FROM (SELECT issued_line, any_value(issued_qty) AS issued, sum(qty) AS used
             FROM traced WHERE issued_line IS NOT NULL GROUP BY issued_line)""",
)
