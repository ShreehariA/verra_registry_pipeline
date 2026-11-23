# Verra Registry Pipeline

Turns the three daily Verra registry exports into a clean, tested data model, with a dashboard on top:
- **issuances:** credits issued to a project;
- **retirements:** credits claimed against emissions;
- **cancellations:** credits removed for administrative reasons.

> Being rebuilt as a lean version. The full README (data model, decisions, live demo) comes with the docs step.

## Quick start

Needs [uv](https://docs.astral.sh/uv/); it installs Python 3.13 if it is missing.

```bash
make setup     # create .venv with the locked dependencies
make check     # lint, type-check and run every test
make build     # build every layer from the newest complete snapshot in data/landing
make query SQL="select count(*) from bronze.retirements"
```

To load another snapshot, put its three files in `data/landing/` (`VerraIssuances_<YYYY-MM-DD>.csv`, `VerraRetirements_<YYYY-MM-DD>.csv`, `VerraCancelled_<YYYY-MM-DD>.csv`) and run `make build`. The newest date with all three files is loaded. `uv run verra build --snapshot 2026-11-17 --landing path/to/folder` picks a date or a folder for one run.

## How it works

Medallion layers, one Parquet file per table and snapshot date:
- **landing:** the raw files, only ever read;
- **bronze:** every row as delivered, with the file, line and checksum it came from; unreadable records go to `bronze.rejected_records` with the reason and their exact text;
- **silver** and **gold:** cleaned tables and the model for the dashboard (in progress).

Settings live in [`pipeline.toml`](pipeline.toml): paths, the file-name pattern, the reject budget and the columns each export must have. The raw files are never changed.

## Layout

```
pipeline.toml          settings: paths, file names, required columns
src/verra_pipeline/    the pipeline: ingest.py, lake.py, config.py, cli.py
tests/                 tests on a fixture snapshot dated 2030-01-15
data/landing/          raw Verra files, never modified
docs/architecture/     diagrams of the data flow and the Google Cloud design
lake/                  generated (git-ignored; `make clean` deletes it)
```
