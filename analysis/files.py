"""The three files at a glance, read byte by byte: size, encoding, line endings, records and odd characters.

Behind docs/data-analysis.md, "The three files at a glance" and "File format". It reads the raw bytes with
Python's csv module on its own, so its counts are a second opinion on the pipeline's reader.
"""

import codecs
import collections
import csv
import io
import re

from common import files

ODD = {
    "no-break spaces": "\u00a0",
    "tabs": "\t",
    "zero-width spaces": "\u200b",
    "replacement marks": "\ufffd",
}
MOJIBAKE = re.compile("\u00c3[\u0080-\u00bf]|\u00e2\u20ac")  # UTF-8 read as Windows-1252, as in StÃ¤dtische

for path in files.values():
    raw = path.read_bytes()
    try:
        text, encoding = raw.decode("utf-8-sig"), "UTF-8"
    except UnicodeDecodeError:
        text, encoding = raw.decode("cp1252", errors="replace"), "not UTF-8"
    lines = io.StringIO(text, newline="").readlines()
    crlf = text.count("\r\n")
    ends_cleanly = text.endswith(("\n", "\r"))
    print(f"\n## {path.name}: {len(raw):,} bytes, {len(lines):,} lines")
    print(f"- encoding: {encoding}; starts with a byte-order mark: {raw.startswith(codecs.BOM_UTF8)}")
    print(f"- line endings: {crlf:,} Windows (CRLF), {text.count(chr(10)) - crlf:,} Unix (LF)")
    print(f"- ends with a newline: {ends_cleanly}")

    reader = csv.reader(lines)
    header = next(reader)
    fields, spans, short = collections.Counter(), [], []
    padded, doubled = collections.Counter(), collections.Counter()
    last = reader.line_num
    for record in reader:
        first, last = last + 1, reader.line_num
        fields[len(record)] += 1
        if last > first:
            spans.append(first)
        if len(record) != len(header):
            short.append((first, len(record)))
            continue
        for name, value in zip(header, record, strict=True):
            padded[name] += value != value.strip()
            doubled[name] += "  " in value
    print(f"- records: {fields.total():,}; fields per record: {dict(fields)} (the header has {len(header)})")
    print(f"- records over several lines (first line of each): {spans}")
    print(f"- records with the wrong number of fields (line, fields): {short}")
    print(f"- spaces before or after a value: {dict(+padded) or 'none'}")
    print(f"- spaces doubled inside a value: {dict(+doubled) or 'none'}")
    print(f"- {', '.join(f'{text.count(char)} {name}' for name, char in ODD.items())}")
    print(f"- mis-encoded sequences such as Ã¤: {len(MOJIBAKE.findall(text))}")
