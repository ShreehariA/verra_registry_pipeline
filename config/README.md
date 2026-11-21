# config/: where things are and how they are named

`pipeline.json` holds every location, file-name pattern, view name and threshold the pipeline uses. Nothing of the kind is fixed in Python. Its rules are in [`src/verra_pipeline/formats/pipeline.schema.json`](../src/verra_pipeline/formats/pipeline.schema.json); editors use that file to autocomplete and check `pipeline.json` as you type, and the pipeline checks it on every run.

## How the pipeline finds its config

The first of these that exists wins:
1. `--config FILE` on the command line.
2. The `VERRA_CONFIG` environment variable.
3. `config/pipeline.json` in the current folder, or in the nearest folder above it, the way git finds its repository.

You can therefore run `verra` from any sub-folder of the repository.

## What is in it

| Key | Today | Meaning |
|---|---|---|
| `root` | `..` | The folder every relative path is resolved from, relative to this config file. Paths never depend on the folder you run from |
| `sources.<system>.landing` | `data/landing` | Where that source system's daily files arrive; only ever read |
| `sources.<system>.file_name` | `{prefix}_{date}.csv` | How its files are named. `{prefix}` comes from each bronze table's `source.file_prefix`, and `{date}` is YYYY-MM-DD |
| `paths.schema` | `schema` | The table definitions (see `schema/README.md`) |
| `paths.lake` | `lake` | Where the layers are written as Parquet |
| `paths.warehouse` | `warehouse/verra.duckdb` | The DuckDB file holding the query views |
| `lake.table_file` | `{layer}/{table}/snapshot_date={date}/data.parquet` | One table's data for one snapshot, under the lake |
| `lake.manifest_file` | `_manifests/snapshot_date={date}/{stage}.json` | A stage's record of a run, under the lake |
| `warehouse.current_view` | `{table}` | View name for the latest snapshot of a table |
| `warehouse.history_view` | `{table}_history` | View name for every snapshot of a table |
| `ingest.max_rejected_share` | `0.01` | Stop when more than this share of a file's lines cannot be read |

Every template must use exactly its placeholders. A missing or unknown placeholder stops the run with a clear message.

## Changing a value for one run

Command-line flags override the config for that run only. Paths given on the command line are relative to the folder you are in.

```bash
uv run verra ingest --landing path/to/drop --lake /tmp/lake --max-rejected-share 0.05
uv run verra ingest --source verra --snapshot 2026-11-17
```

## Another environment

Another environment is just another file, for example `config/ci.json`, or `config/gcp.json` in the cloud step. Select it with `--config` or `VERRA_CONFIG`.

Cloud storage URIs such as `gs://...` are refused with a clear message until the cloud step adds a Cloud Storage lake. Until then they would not work, so they are refused rather than silently mishandled.
