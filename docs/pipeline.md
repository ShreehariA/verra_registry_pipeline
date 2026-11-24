# How a build works

`make build` (or `uv run verra build`) turns one day's three files into every table, in one process, in about a second. This page follows a build from the raw files to the lake, and shows how each step keeps the pipeline's promises.

![Data architecture, as built](architecture/verra-pipeline-as-built-data.png)

## The steps

1. **Find the snapshot.** Files are named `<prefix>_<YYYY-MM-DD>.csv`. The newest date that has all three files is built, and the report's first line names it. An incomplete date is skipped without a word, so check that date. `--snapshot` picks a date, and then a missing file is an error.
2. **Read and check every file** (`ingest.py`). Nothing is written yet.
3. **Load bronze** into one in-memory DuckDB database.
4. **Build silver and gold** by running the SQL files in `sql/` (`transform.py`).
5. **Run the quality gate** (`sql/checks.sql`). If an error check fails, the build stops here with one sentence, and nothing is written.
6. **Write** every table to the lake, then the manifest, last (`lake.py`).

## Reading a file without trusting it

- **Read once, as bytes.** Each file's SHA-256 checksum goes into the manifest and onto every bronze row. The raw file is never opened for writing.
- **Text:** UTF-8, with or without a byte-order mark. A file that isn't UTF-8 is read as Windows-1252. Each of these is reported as a finding.
- **Records:** Python's `csv` module follows the quotes, so a line break inside a field stays in its record. Windows and Unix line endings both work, and each record keeps the line it starts on.
- **Quarantine:** a record with the wrong number of fields, such as a cut-off last line, goes to `bronze.rejected_records` with the reason and its exact text. The build carries on.
- **The reject budget:** a file with more than 1% of its lines unreadable is refused, and the run stops. The budget counts lines, not records, because one stray quote can swallow many lines into a single record.

## Headers matched by name

- Headers are normalised (`Retirement QTY` becomes `retirement_qty`) and matched by name, in any order.
- `pipeline.toml` lists each export's required and optional columns. A missing required column stops the run and names the column. A missing optional column is loaded empty, with a finding.
- If Verra renames a header, one alias line in `pipeline.toml` maps the new name to the old one.
- A new column is kept in bronze and listed in the manifest.

## Bronze: as delivered, plus where it came from

Every value stays text, exactly as delivered. Four lineage columns say where each row came from: `_snapshot_date`, `_source_file`, `_source_line` and `_file_sha256`. So any number on the dashboard can be traced back to lines in a raw file.

## Silver and gold

The SQL files run in a fixed order: `macros.sql`, then `silver/`, then `gold/`. Python only runs them, and names a broken file in one line. How each value is read and modelled is in [the data model](data-model.md).

## The quality gate

19 checks run on the finished tables, before anything is written: 6 errors, which stop the build, and 13 warnings, which are reported. They are in [checks and tests](quality.md).

## Writing: all or nothing

1. Every check runs before the first write.
2. Each file is written under a temporary name, then renamed over the target, so a reader never sees half a file.
3. A rebuild of a day first removes that day's manifest, so the day stays hidden until it's whole again.
4. The manifest is written last. It records each input file, its checksum, the columns found, the rows read, loaded and quarantined, the findings, the gate's results and the credit totals.
5. Readers (`verra query` and the dashboard) only see dates that have a manifest.

## The lake

```
lake/
  bronze/issuances/snapshot_date=2026-11-17/data.parquet    and retirements, cancellations, rejected_records
  silver/…/snapshot_date=2026-11-17/data.parquet
  gold/…/snapshot_date=2026-11-17/data.parquet
  _manifests/snapshot_date=2026-11-17/build.json
```

Every snapshot stays in its own folder. `verra query` and the dashboard create views in memory over the newest finished snapshot. Nothing locks the files, so a build can run while the dashboard is open.

## Same input, same bytes

- DuckDB runs on one thread, and every SQL file sorts its output (`ORDER BY`), so rows always come out in the same order;
- nothing written holds a timestamp;
- package versions are pinned in `uv.lock`.

A test rebuilds and compares every file. Built in the Docker image on Linux, the 15 files are identical to the ones built on macOS, checksum for checksum.

## Settings and the command line

- **`pipeline.toml`:** where the files are, how they're named, the reject budget, and the columns each export must have. Paths are relative to the file.
- **`verra build`** takes `--snapshot <date>`, `--landing <folder>` and `--lake <folder>` for one run, and `verra --config <file> build` reads other settings.
- **`verra query "<SQL>"`** runs SQL on the newest finished snapshot (`make query SQL="…"`).
- **Errors are one sentence,** for example: `error: the quality gate failed, so nothing was written: every quantity is a whole number above zero: 1 row(s)`.

```bash
make build                                      # the newest complete snapshot in data/landing
make clean build                                # from an empty lake, so readers show exactly this snapshot
uv run verra build --snapshot 2026-11-17        # a given date
uv run verra build --landing <folder> --lake <folder>
uv run verra --config other.toml build          # other settings
make query SQL="select * from bronze.rejected_records"
```

Step by step, with what you should see: [the operating procedure](sop.md).
