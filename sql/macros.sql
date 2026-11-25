-- Each macro turns delivered text into a value, or NULL when it can't be read; checks.sql counts the NULLs.

-- '19 Mar 2009' (issuances, retirements) or '01-Apr-09' (cancellations; 00-68 is 2000-2068); ISO as a fallback.
CREATE MACRO parse_date(text) AS try_strptime(trim(text), ['%d %b %Y', '%d-%b-%y', '%Y-%m-%d'])::DATE;

-- A vintage is one year, '2013', or a range, '2007 - 2008': its first and its last year.
CREATE MACRO vintage_start(vintage) AS try_cast(regexp_extract(vintage, '^\s*(\d{4})', 1) AS INTEGER);
CREATE MACRO vintage_end(vintage) AS try_cast(regexp_extract(vintage, '(\d{4})\s*$', 1) AS INTEGER);

-- A serial number starts with the batch, the first serial and the last: '10026-172542403-172547402-VCS-…'.
-- The middle differs between the old and new formats, so only the start is read.
CREATE MACRO serial_part(serial, part) AS try_cast(regexp_extract(serial, '^\s*(\d+)-(\d+)-(\d+)-', part) AS BIGINT);

-- Trimmed, with every run of spaces, tabs and no-break spaces made one space; blank becomes NULL.
CREATE MACRO clean_text(text) AS nullif(trim(regexp_replace(text, '[\s\p{Z}\x{200B}]+', ' ', 'g')), '');

-- The words of a name: lower case, no accents, anything but letters and digits made a space. Letters of every
-- alphabet are kept, so a Chinese company name doesn't become blank.
CREATE MACRO name_words(name) AS
    trim(regexp_replace(lower(strip_accents(coalesce(name, ''))), '[^\p{L}\p{N}]+', ' ', 'g'));

-- One key per owner, whatever the spelling: 'Interface, Inc.', 'Interface Inc' and 'INTERFACE' are 'interface'.
-- A legal form at the end is dropped; blanks and placeholders ('_', 'N/A', 'Other') become 'unspecified'.
CREATE MACRO owner_key(name) AS CASE
    WHEN replace(name_words(name), ' ', '') IN ('', 'na', 'none', 'null', 'other', 'unknown', 'unspecified')
        THEN 'unspecified'
    ELSE replace(regexp_replace(name_words(name),
        '( (inc|incorporated|ltd|ltda|limited|llc|plc|gmbh|ag|sa|s a|sas|s a s|spa|s p a|srl|bv|nv|pty|co|corp|corporation|company))+$',
        ''), ' ', '')
END;

-- A quantity or an ID: digits only, else NULL, which the gate counts. A plain cast is not enough: try_cast reads
-- '12.5' as 13 and '1e3' as 1000 without a word.
CREATE MACRO whole_number(text) AS try_cast(regexp_extract(trim(text), '^\d+$') AS BIGINT);
