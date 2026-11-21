# Step 1: Ingest → Bronze

**Goal:** load one day's three Verra files into the **bronze** layer exactly as delivered. Nothing is cleaned here. Every row stays traceable to its file and line, and anything unreadable is set aside, never dropped silently.

This is the first box of the data diagram: `Landing → Ingest → Bronze` (with quarantine).

> **Updated in step 1b:** columns now come from `schema/bronze/*.json` and locations from `config/pipeline.json`.
> This page describes the current behaviour; [01b-schema-and-config.md](01b-schema-and-config.md) explains that change.

## What I built

| File | What it is for |
|---|---|
| `pyproject.toml`, `uv.lock`, `.python-version` | The project: Python 3.13, pinned dependencies (DuckDB, pyarrow), tool settings for ruff, mypy and pytest |
| `Makefile` | The commands; run `make` to list them |
| `data/landing/` | The three raw files, moved here unchanged (checksums verified before and after) |
| `src/verra_pipeline/snapshot.py` | `SnapshotFinder`: finds the newest date that has **every** file the schema expects |
| `src/verra_pipeline/ingest/csv_reader.py` | `CsvFileReader`: records facts about the file, parses it, quarantines broken records |
| `schema/bronze/*.json` (step 1b) | Which columns each file has and which are required (was `ingest/contracts.py`) |
| `src/verra_pipeline/ingest/header.py` | `HeaderMatcher`: matches headers to schema columns; stops the run if a required column is missing or repeated |
| `src/verra_pipeline/ingest/reject_budget.py` | `RejectBudget`: stops the run if more than 1 % of a file's lines are unreadable |
| `src/verra_pipeline/ingest/loader.py` | `FileLoader`: read, then check, one file |
| `src/verra_pipeline/ingest/bronze.py` | The shape of the bronze tables and the quarantine table, with lineage columns |
| `src/verra_pipeline/ingest/report.py` | What the run found: the printed summary and the JSON manifest |
| `src/verra_pipeline/ingest/stage.py` | `IngestStage`: runs the steps in order; only orchestrates |
| `src/verra_pipeline/lake.py` | `Lake` interface plus `LocalLake`: Parquet files, one partition per snapshot date (layout from the config), atomic writes |
| `src/verra_pipeline/warehouse.py` | `LocalWarehouse`: DuckDB views over the lake, so you can query it with SQL |
| `src/verra_pipeline/cli.py` | The `verra` command: `verra ingest`, `verra query` and (step 1b) `verra schema` |
| `src/verra_pipeline/errors.py`, `config.py`, `text_table.py` | Error types, the config loader (step 1b), terminal tables |
| `tests/` | One test file per class, plus integration tests on a fake snapshot dated 2030-01-15 (107 tests after step 1b) |

## What it does

```
data/landing/VerraIssuances_2026-11-17.csv ─┐
data/landing/VerraRetirements_2026-11-17.csv ─┼─ SnapshotFinder: newest date with all 3 files
data/landing/VerraCancelled_2026-11-17.csv  ─┘
        │
        ▼  for each file (FileLoader)
   CsvFileReader     checksum, encoding, BOM, line endings, cut-off check; parse; quarantine bad records
   HeaderValidator   required columns present, none repeated, new columns reported
   RejectBudget      no more than 1 % of lines unreadable
        │
        ▼  only after ALL three files pass (so bronze never mixes two snapshots)
   LocalLake         lake/bronze/<table>/snapshot_date=2026-11-17/data.parquet
                     lake/bronze/rejected_records/...
                     lake/_manifests/snapshot_date=2026-11-17/ingest_verra.json
   LocalWarehouse    views bronze.<table> (latest snapshot) and bronze.<table>_history (all snapshots)
```

**Rules worth knowing**
- **All or nothing.** If one file fails a check, nothing is written for that snapshot.
- **Re-runs are safe.** Re-running a date replaces exactly that date's partition, so the second run gives byte-identical files. Other dates are never touched.
- **Values stay as text,** exactly as delivered. An empty retirement date stays `''`; deciding what it means is silver's job, in step 3.
- **Every row carries lineage:**
  - `_snapshot_date`
  - `_source_file`
  - `_source_line`: the line the record starts on; the header is line 1
  - `_file_sha256`
- **Columns are matched by name,** so a reordered file still loads. A new column is kept and reported. A missing required column stops the run.

## How to run it

```bash
make setup     # once: creates .venv with the pinned versions (needs uv)
make ingest    # load the newest complete snapshot from data/landing into bronze
```

Other ways to run it:

```bash
uv run verra ingest --snapshot 2026-11-17             # a specific date
uv run verra ingest --landing /path/to/another/drop   # another folder with the three files
uv run verra --help                                    # every command and option
```

## What you should see

```
Source verra, snapshot 2026-11-17, read from data/landing

table          file                             rows read  loaded  quarantined  encoding   line endings
-------------  -------------------------------  ---------  ------  -----------  ---------  ------------
cancellations  VerraCancelled_2026-11-17.csv          471     471            0  utf-8      CRLF
issuances      VerraIssuances_2026-11-17.csv        2,724   2,724            0  utf-8      LF
retirements    VerraRetirements_2026-11-17.csv     23,276  23,275            1  utf-8-sig  LF

Findings
  VerraCancelled_2026-11-17.csv: uses CRLF line endings
  VerraRetirements_2026-11-17.csv: starts with a byte-order mark, which was removed
  VerraRetirements_2026-11-17.csv: does not end with a newline, so its last record may be cut off
  VerraRetirements_2026-11-17.csv: line 23284 quarantined: expected 20 fields, found 9; the file ends inside this record, so it was probably cut off

Written to lake; quarantine table: rejected_records
Manifest: lake/_manifests/snapshot_date=2026-11-17/ingest_verra.json
Schema fingerprint: ...
```

Each finding is a real problem in the delivered files:
- **Retirements** is UTF-8 with a byte-order mark, and it was cut off partway through its last record.
- **Cancellations** uses Windows line endings.

The reader handles all of these. The cut-off record is not lost: it sits in `bronze.rejected_records` with its exact text.

## Look at the results yourself

```bash
# rows per table
uv run verra query "select 'issuances' t, count(*) n from bronze.issuances
                    union all select 'retirements', count(*) from bronze.retirements
                    union all select 'cancellations', count(*) from bronze.cancellations"

# the quarantined record: why, and its exact text
uv run verra query "select target_table, _source_line, reason, raw_text from bronze.rejected_records"

# where any row came from
uv run verra query "select serial_number, retirement_qty, _source_file, _source_line
                    from bronze.retirements order by _source_line limit 5"

# the 19 retirements Verra itself flagged (they have no date; silver will keep them)
uv run verra query "select count(*), sum(cast(retirement_qty as bigint)) from bronze.retirements
                    where validation_status = 'FLAG'"

# the machine-readable record of the run: checksums, counts, findings
cat lake/_manifests/snapshot_date=2026-11-17/ingest_verra.json
```

Expected results:
- **Rows per table:** 2,724, 23,275 and 471.
- **Quarantine:** 1 row, line 23284.
- **Flagged retirements:** 19 rows, 209,992 credits.

## How to test it

```bash
make check    # lint (ruff) + type check (mypy, strict) + all tests
make test     # only the tests
```

| Test file | Proves |
|---|---|
| `tests/unit/test_snapshot_finder.py` | The newest *complete* date is chosen; a missing file or date gives a clear error; other files are ignored |
| `tests/unit/test_csv_reader.py` | Line numbers; quoted commas and line breaks; BOM; CRLF; quarantine with exact text; cut-off detection; blank lines; the Windows-1252 fallback; checksum; files with no header |
| `tests/unit/test_header_matcher.py` | Headers matched by name or alias, in any order; new columns kept; missing or repeated columns stop the run |
| `tests/unit/test_reject_budget.py` | A few bad lines are fine; too many stop the run; counted in lines, so one broken quote cannot hide thousands of lines |
| `tests/unit/test_local_lake.py` | One partition per date; re-writing replaces only that date; no temporary files left; empty tables keep their types |
| `tests/unit/test_loader.py`, `test_text_table.py` | Small pieces: a file with only a header, terminal tables |
| `tests/integration/test_ingest_stage.py` | The whole stage on a fake snapshot dated **2030-01-15** with the same quirks; lineage; quarantine; **identical second run**; nothing written when one file is bad |
| `tests/integration/test_cli.py` | `verra ingest` then `verra query` end to end; errors are one readable line |

## Try breaking it

These work on a copy in `scratch/`, which git ignores, so `data/landing` is never touched. Each option is written out in full, which works in zsh (the macOS default shell) as well as bash.

```bash
mkdir -p scratch/landing && cp data/landing/*.csv scratch/landing/

# 1. A missing file: the snapshot is incomplete, so nothing loads
rm scratch/landing/VerraCancelled_2026-11-17.csv
uv run verra ingest --landing scratch/landing --lake scratch/lake --warehouse scratch/verra.duckdb
#    error: no date has all 3 expected files in /…/scratch/landing (2026-11-17 has 2 of 3)
#    (errors show full paths, so they are unambiguous in logs)
cp data/landing/VerraCancelled_2026-11-17.csv scratch/landing/

# 2. A renamed column: the schema catches it and names the header it expected
sed -i '' '1s/Retirement QTY/Quantity Retired/' scratch/landing/VerraRetirements_2026-11-17.csv
uv run verra ingest --landing scratch/landing --lake scratch/lake --warehouse scratch/verra.duckdb
#    error: VerraRetirements_2026-11-17.csv: required columns are missing: retirement_qty (header 'Retirement QTY')
cp data/landing/VerraRetirements_2026-11-17.csv scratch/landing/

# 3. A stricter reject budget: the one cut-off line is now too many
uv run verra ingest --landing scratch/landing --lake scratch/lake --warehouse scratch/verra.duckdb --max-rejected-share 0.00001
#    error: VerraRetirements_2026-11-17.csv: 1 of 23,283 lines (0.0043%) could not be read; at most 0.001% is allowed

# 4. Re-runs are identical: the checksums match after a second run
uv run verra ingest --landing scratch/landing --lake scratch/lake --warehouse scratch/verra.duckdb > /dev/null
shasum scratch/lake/bronze/*/*/data.parquet
uv run verra ingest --landing scratch/landing --lake scratch/lake --warehouse scratch/verra.duckdb > /dev/null
shasum scratch/lake/bronze/*/*/data.parquet

rm -rf scratch    # tidy up
```

After cases 1–3, `scratch/lake` does not exist: a failed run writes nothing.

## How the code follows Uncle Bob's principles

- **One reason to change per class.**
  - `CsvFileReader` only parses.
  - `HeaderValidator` only checks columns.
  - `RejectBudget` only decides "too broken".
  - `LocalLake` only stores.
  - `IngestStage` only runs the others in order.
- **Depend on abstractions.** `IngestStage` receives its collaborators in its constructor and writes through the `Lake` interface. A Google Cloud Storage lake can replace `LocalLake` in step 7 without changing a line of the stage, which is the open/closed principle.
- **Composition root.** `cli.py` is the only place that knows the concrete classes and the terminal. That is why every stage can be tested on its own.
- **Errors are exceptions with a clear sentence,** never return codes. They all share one base, `PipelineError`, so the command line prints one line instead of a stack trace.
- **Value objects are frozen dataclasses.** `Snapshot`, `FileProfile`, `RejectedRecord` and `TableData` cannot be changed by accident after they are created.
- **Boundaries:** pyarrow and DuckDB are used only in `lake.py` and `warehouse.py`. Everything else works on our own plain types.

## What is not done yet

- **Cleaning** (dates, quantities, serial numbers, owner names): step 2 builds the cleaning library, and step 3 applies it to make silver.
- **A run catalog:** today the run record is a JSON manifest in the lake. Step 5 adds the catalog (SQLite locally, Firestore on Google Cloud) and the `verra catalog` and `verra trace` commands.
- **Very large files:** rows are held in memory, which is fine at this size (8 MB for the biggest file). For 100× the volume, the reader would stream in batches; the interfaces stay the same.
