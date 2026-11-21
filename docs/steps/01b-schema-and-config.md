# Step 1b: tables in `schema/`, locations in `config/`

**Goal:** nothing structural is hard-coded.
- **Tables and columns** are declared in JSON (`schema/`), for every layer.
- **Locations, file names, view names and thresholds** are declared in JSON (`config/pipeline.json`).

Adding, removing or renaming a column, or moving a folder, is a JSON edit. The code only holds behaviour: how to read a CSV, how to fill a lineage value, how to write Parquet.

## What changed and why

| Before (step 1) | Now | Why it matters in production |
|---|---|---|
| Required and known columns in `ingest/contracts.py` | `schema/bronze/<table>.json`, one file per table | A schema change is reviewed as data, not code; silver and gold will use the same mechanism |
| File prefixes in an `Entity` enum | `source.file_prefix` in each bronze table | A new export is one new JSON file |
| `data/landing`, `lake`, `warehouse/...` in `config.py` | `config/pipeline.json`, found via `--config`, then `$VERRA_CONFIG`, then the nearest `config/pipeline.json` | Each environment (local, CI, Google Cloud) is its own config file; paths never depend on the folder you run from |
| `{prefix}_{date}.csv` and the lake layout in code | Templates in the config | Another naming convention or lake layout is a config edit |
| Lineage and quarantine columns in Python | `shared/bronze_lineage.json` and `bronze/rejected_records.json`, values filled through `"generated"` | Even the pipeline's own columns are declared |
| One manifest per date | One per source system and date (`ingest_verra.json`), with a schema fingerprint | Several source systems never overwrite each other; every partition can be traced to the schema that produced it |
| Columns in file order | Columns in schema order; a missing optional column becomes NULL; unknown columns are kept, or dropped if the table says so | Every snapshot's Parquet has the same columns, so the history views union cleanly |

## What I built

| File | What it is for |
|---|---|
| `schema/bronze/*.json`, `schema/shared/bronze_lineage.json` | The four bronze tables and the shared lineage columns |
| `schema/README.md` | The format, plus a "common changes" table (rename, add, drop, require, new export, new system) |
| `config/pipeline.json`, `config/README.md` | Every location, naming pattern, view name and threshold, and how the config is found and overridden |
| `src/verra_pipeline/formats/*.schema.json` | The rules for table files, column sets and the config (JSON Schema), shipped with the code |
| `src/verra_pipeline/json_formats.py` | The only module that uses jsonschema: read a JSON file, check it against its format |
| `src/verra_pipeline/schema/model.py` | `ColumnSpec`, `TableSpec`, `SourceSpec`, `ForeignKey`: the schema as plain, frozen values |
| `src/verra_pipeline/schema/registry.py` | `SchemaRegistry`: loads the folder, runs the cross-checks, looks tables up, computes the fingerprint |
| `src/verra_pipeline/config.py` | `PipelineConfig` (loaded and checked) and `ConfigLocator` (how the file is found) |
| `src/verra_pipeline/ingest/header.py` | `HeaderMatcher`: matches file headers to schema columns by `source_header` or `aliases` |
| `src/verra_pipeline/ingest/bronze.py` | Builds bronze rows in schema order; `GENERATED_VALUES` says how each generated value is filled |
| `src/verra_pipeline/ingest/stage.py` | `IngestPlan` (what one run loads) and `IngestStage` |
| `verra schema` | A new command: list the tables, or one table's columns |

Removed: `ingest/contracts.py` and the `Entity` enum.

## How to run it

The commands are the same as in step 1:

```bash
make ingest                                  # or: uv run verra ingest
uv run verra schema                          # the tables the schema declares
uv run verra schema --table retirements      # one table's columns and where each value comes from
uv run verra query "select count(*) from bronze.retirements"
```

The pipeline now finds `config/pipeline.json` by itself, from any folder inside the repository:

```bash
cd src/verra_pipeline && uv run verra query "select count(*) from bronze.issuances"
```

## What you should see

`make ingest` gives the same numbers as before; tables are now listed by name:

```
Source verra, snapshot 2026-11-17, read from data/landing

table          file                             rows read  loaded  quarantined  encoding   line endings
-------------  -------------------------------  ---------  ------  -----------  ---------  ------------
cancellations  VerraCancelled_2026-11-17.csv          471     471            0  utf-8      CRLF
issuances      VerraIssuances_2026-11-17.csv        2,724   2,724            0  utf-8      LF
retirements    VerraRetirements_2026-11-17.csv     23,276  23,275            1  utf-8-sig  LF
...
Manifest: lake/_manifests/snapshot_date=2026-11-17/ingest_verra.json
Schema fingerprint: ...
```

`uv run verra schema --table retirements` shows 20 columns read from the file and 4 lineage columns, each with where its value comes from:

```
 #  column            type     nullable  filled from                          description
11  retirement_qty    text     yes       header 'Retirement QTY' (required)   Number of credits retired in this record...
21  _snapshot_date    date     no        generated: snapshot_date             Date of the snapshot the row was loaded...
```

The quarantine table's columns are now `target_table`, `line_count`, `reason` and `raw_text`, followed by the same four lineage columns as every bronze table:

```bash
uv run verra query "select target_table, _source_line, reason from bronze.rejected_records"
```

## Try it: change only JSON, never code

These work on copies, so the real data, schema and config are not touched. They are written for zsh, the macOS default shell.

```bash
mkdir -p scratch/landing && cp data/landing/*.csv scratch/landing/ && cp -r schema scratch/schema

# 1. Verra renames a header: the run stops and says which header it expected
sed -i '' '1s/Retirement QTY/Quantity Retired/' scratch/landing/VerraRetirements_2026-11-17.csv
uv run verra ingest --landing scratch/landing --schema scratch/schema --lake scratch/lake --warehouse scratch/verra.duckdb
#    error: VerraRetirements_2026-11-17.csv: required columns are missing: retirement_qty (header 'Retirement QTY')

# 2. Fix it in JSON: add the new header as an alias. Open scratch/schema/bronze/retirements.json and change
#      "source_header": "Retirement QTY", "required": true,
#    to
#      "source_header": "Retirement QTY", "aliases": ["Quantity Retired"], "required": true,
uv run verra ingest --landing scratch/landing --schema scratch/schema --lake scratch/lake --warehouse scratch/verra.duckdb
#    loads again: 23,275 retirements

# 3. Stop loading a column: in scratch/schema/bronze/issuances.json, delete the "verifier" entry and add
#      "unknown_columns": "drop",
#    next to "layer"; then run the same ingest command again
#    Findings: VerraIssuances_2026-11-17.csv: has columns the schema does not declare, left out: verifier

# 4. Another file-naming convention, set only in a config copy
mkdir -p scratch/renamed
for f in data/landing/*.csv; do b=$(basename $f .csv); cp $f "scratch/renamed/export-${b##*_}-${b%_*}.txt"; done
cp config/pipeline.json config/scratch.json
#    In config/scratch.json, set sources.verra to
#      { "landing": "scratch/renamed", "file_name": "export-{date}-{prefix}.txt" }
#    and set paths.lake to "scratch/lake2"
VERRA_CONFIG=config/scratch.json uv run verra ingest

rm -rf scratch config/scratch.json    # tidy up
```

I ran all four: each behaves as shown.

## How to test it

`make check` runs lint, strict type checks and **107 tests** in under a second.

| New or changed test file | Proves |
|---|---|
| `tests/unit/test_schema_registry.py` | The real schema loads; 11 kinds of broken definition are refused with the file and the reason; the fingerprint is stable and changes with the definitions; the generated keys in code match the format |
| `tests/unit/test_config.py` | The real config loads; paths do not depend on the current folder; lookup order flag → env → nearest folder; templates need exactly their placeholders; `gs://` is refused clearly; source selection; one-run overrides |
| `tests/unit/test_header_matcher.py` | Matching by header and by alias, in any order; missing required (stop) and optional (NULL); unknown columns kept, prefixed if they clash; repeated headers stop |
| `tests/unit/test_warehouse.py` | View names come from the config; history views survive a column added later (`union_by_name`); unsafe SQL names are refused |
| `tests/integration/test_ingest_stage.py` | Everything from step 1, plus columns in schema order, the manifest's system and fingerprint, and **JSON-only changes:** an alias loads a renamed header, and a removed column is kept or dropped as the table says |
| `tests/integration/test_cli.py` | Config from `--config` and from `VERRA_CONFIG`; flags override for one run; `verra schema` listings |

## Design notes

- **Structure is data, behaviour is code.** JSON says which columns exist and where values come from. Python says how to read a CSV and how to fill `source_line`.
- **Each third-party library stays in one module:**
  - jsonschema in `json_formats.py`
  - pyarrow in `lake.py`
  - DuckDB in `warehouse.py`
- **Fail early, with a sentence.** A broken schema or config stops the run before any data is touched, naming the file, the place and the reason.
- **Built for growth:**
  - several source systems, each with its own quarantine table and manifest
  - per-environment config files
  - a clear refusal of `gs://` until the cloud step
  - history views that tolerate schema evolution
  - a schema fingerprint in every manifest
