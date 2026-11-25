"""docs/data-analysis.md, "Owners (question 3)": blanks, spellings, mis-encoded names, and the ranking.

The owner key here is the analysis's own, written before the pipeline's; a test holds the pipeline to it.
"""

import pyarrow as pa
from common import con, show


def repair(text: str) -> str:
    """UTF-8 that was read as Windows-1252 before Verra exported it: 'StÃ¤dtische' back to 'Städtische'."""
    try:
        return text.encode("cp1252").decode("utf-8")
    except UnicodeError:
        return text


names = [name for (name,) in con.sql("SELECT DISTINCT beneficial_owner FROM retirements").fetchall()]
con.register("repairs", pa.table({"raw": names, "repaired": [repair(name) for name in names]}))

# Each cleaning step applied on top of the previous one, then the final key: legal forms at the end dropped,
# and every blank or placeholder made 'unspecified'
con.execute(r"""
    CREATE TABLE owners AS
    SELECT r.beneficial_owner AS raw, r.retirement_qty::BIGINT AS qty,
        r.project_id, r.project_name, r.vintage,
        lower(trim(regexp_replace(r.beneficial_owner, '\s+', ' ', 'g'))) AS spaces_and_case,
        regexp_replace(lower(strip_accents(r.beneficial_owner)), '[^a-z0-9]+', '', 'g') AS a_to_z_only,
        trim(regexp_replace(lower(strip_accents(f.repaired)), '[^\p{L}\p{N}]+', ' ', 'g')) AS words,
        regexp_replace(words, '( (inc|incorporated|ltd|ltda|limited|llc|plc|gmbh|ag|sa|s a|sas|s a s'
            || '|spa|s p a|srl|bv|nv|pty|co|corp|corporation|company))+$', '') AS without_legal_form,
        CASE WHEN replace(words, ' ', '') IN ('', 'na', 'none', 'null', 'other', 'unknown', 'unspecified')
            THEN 'unspecified' ELSE replace(without_legal_form, ' ', '') END AS owner_key
    FROM retirements AS r JOIN repairs AS f ON f.raw = r.beneficial_owner
""")
show(
    "Retired credits with no owner: blank, and with the placeholders added",
    """SELECT count(*) FILTER (raw = '') AS blank_rows, sum(qty) FILTER (raw = '') AS blank_credits,
           count(*) FILTER (owner_key = 'unspecified') AS unspecified_rows,
           sum(qty) FILTER (owner_key = 'unspecified') AS unspecified_credits,
           round(100 * unspecified_credits / sum(qty), 1) AS percent_of_retired
       FROM owners""",
)
show(
    "The placeholders: owner names that are not names",
    """SELECT raw AS written_as, count(*) AS rows, sum(qty) AS credits FROM owners
       WHERE owner_key = 'unspecified' AND raw <> '' GROUP BY 1 ORDER BY credits DESC""",
)
show(
    "The largest retirers as delivered: a placeholder ranks 5th",
    """SELECT raw AS owner, sum(qty) AS credits FROM owners WHERE raw <> ''
       GROUP BY 1 ORDER BY credits DESC LIMIT 5""",
)
show(  # the pattern is Ã then a byte from 0x80 to 0xBF (as in Ã¤), or â€: UTF-8 read as Windows-1252
    "Owner names that look mis-encoded, and the repair; empty when it fails, and the name stays as delivered",
    r"""SELECT raw, CASE WHEN repaired <> raw THEN repaired END AS repaired, count(*) AS rows
        FROM retirements AS r JOIN repairs ON repairs.raw = r.beneficial_owner
        WHERE regexp_matches(raw, '\x{C3}[\x{80}-\x{BF}]|\x{E2}\x{20AC}')
        GROUP BY ALL ORDER BY repaired NULLS LAST, raw""",
)
show(
    "The usual 'keep a to z and 0 to 9' rule blanks names in other alphabets; the key keeps them",
    """SELECT DISTINCT raw, owner_key FROM owners
       WHERE a_to_z_only = '' AND owner_key <> 'unspecified' ORDER BY raw""",
)
show(
    "Distinct owners after each step",
    """SELECT count(DISTINCT raw) FILTER (raw <> '') AS as_delivered,
           count(DISTINCT spaces_and_case) FILTER (raw <> '') AS spaces_and_case,
           count(DISTINCT owner_key) FILTER (owner_key <> 'unspecified') AS named_owners_by_key
       FROM owners""",
)
show(
    "The largest retirers after cleaning, with the spellings merged into each",
    """SELECT first(raw ORDER BY spelling_credits DESC, raw) AS owner, sum(spelling_credits) AS credits,
           count(*) AS spellings, string_agg(raw, ' | ' ORDER BY spelling_credits DESC, raw) AS written_as
       FROM (SELECT owner_key, raw, sum(qty) AS spelling_credits FROM owners
             WHERE owner_key <> 'unspecified' GROUP BY ALL)
       GROUP BY owner_key ORDER BY credits DESC LIMIT 10""",
)
show(
    "What the 10 largest retire",
    """WITH top AS (SELECT owner_key, sum(qty) AS credits FROM owners WHERE owner_key <> 'unspecified'
                   GROUP BY 1 ORDER BY credits DESC LIMIT 10)
       SELECT owner_key, project_id, any_value(project_name) AS project, sum(qty) AS credits,
           string_agg(DISTINCT vintage, ', ' ORDER BY vintage) AS vintages
       FROM owners JOIN top USING (owner_key)
       GROUP BY owner_key, project_id, top.credits ORDER BY top.credits DESC, credits DESC""",
)
show(
    "Owners that are crypto wallets",
    """SELECT count(*) AS rows, sum(qty) AS credits FROM owners
       WHERE regexp_matches(raw, '^0x[0-9a-fA-F]{40}$')""",
)
show(
    "Blank owners whose Retirement Reason Details name someone",
    """SELECT count(*) AS blank_owner_rows,
           count(*) FILTER (retirement_reason_details ILIKE '%behalf%') AS say_on_behalf_of,
           count(*) FILTER (retirement_reason_details ILIKE '%interface%') AS name_interface,
           sum(retirement_qty::BIGINT) FILTER (retirement_reason_details ILIKE '%interface%')
               AS interface_credits
       FROM retirements WHERE beneficial_owner = ''""",
)
