"""Every column of every file: how many values are blank, how many are distinct, and the most common ones."""

from common import con

for table in ("issuances", "retirements", "cancellations"):
    columns = [name for name in con.sql(f"SELECT * FROM {table} LIMIT 0").columns if not name.startswith("_")]
    print(f"\n## {table}: {con.sql(f'SELECT count(*) FROM {table}').fetchall()[0][0]:,} rows")
    for column in columns:
        [(blank, distinct)] = con.sql(
            f"SELECT count(*) FILTER ({column} = ''), count(DISTINCT {column}) FROM {table}"
        ).fetchall()
        top = con.sql(
            f"SELECT {column}, count(*) AS n FROM {table} GROUP BY 1 ORDER BY n DESC, 1 LIMIT 3"
        ).fetchall()
        most = "; ".join(f"{(value or '')[:50]!r} {n:,} times" for value, n in top)
        print(f"- {column}: {blank:,} blank, {distinct:,} distinct. Most common: {most}")
