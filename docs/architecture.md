# Architecture

Two designs, drawn the same way so they compare page by page:
- **As built** (`architecture/verra-pipeline-as-built.drawio`): what this repository runs, locally and in the cloud demo.
- **Production** (`architecture/verra-pipeline.drawio`): where it would go with daily automation, many users and a team.

Open them in [app.diagrams.net](https://app.diagrams.net) (File → Open from → Device).

## Principles

1. **Raw files are evidence.** They're only read, and every row keeps its file and line.
2. **Check everything, then write.** Nothing is written until every check has passed.
3. **Readers see only finished snapshots.** The manifest is written last.
4. **Same input, same output:** the same bytes on the same machine, and the same data on any machine.
5. **Flag, never drop.** Problems are counted and shown, not filtered away.
6. **Settings are data, meaning is SQL, mechanics are Python:** `pipeline.toml`, `sql/`, `src/`.
7. **The least machinery that keeps those promises.** Each piece of the production design is added when it's needed.

## As built

![Data architecture, as built](architecture/verra-pipeline-as-built-data.png)

![Infrastructure, as built](architecture/verra-pipeline-as-built-infra.png)

## Production design

![Data architecture, production](architecture/verra-pipeline-data.png)

![Infrastructure, production](architecture/verra-pipeline-infra.png)

## The demo against the production design

Same shape: Cloud Run, a Cloud Storage lake, a Streamlit dashboard, and one service account per job. The demo leaves out what only pays off with daily automation, many users or a team.

| Piece | Production | Demo | Add it when |
|---|---|---|---|
| Starting a run | Eventarc, when a file lands | `deploy/gcp.sh run` | Files arrive daily with nobody watching |
| Ordering the steps | Cloud Workflows | One job runs every step | Steps need their own retries or alerts |
| Storage | A landing bucket and a lake bucket | One bucket | Raw files need other access rules |
| Run record | Firestore | The manifest in the lake | You need a history of runs |
| Serving gold | BigQuery | DuckDB in the dashboard | Many users, or far more data |
| Dashboards | Streamlit and Looker Studio | Streamlit | Business users build their own reports |
| Infrastructure | Terraform, its state in a bucket, a project per environment | Terraform, its state on your machine | A team, or several environments |
| Releases | CI builds, tests and deploys | CI checks and tests; you deploy | Frequent releases by several people |

## The path to production

1. **Schedule it:** start the job when a full day's files arrive.
2. **Record every run,** with its checksums and gate results, and alert on a failed gate or a new warning.
3. **Serve gold from BigQuery,** for analysts and Looker Studio.
4. **Share the infrastructure:** keep Terraform's state in a bucket, and give dev and prod their own projects.
5. **Deploy from CI:** show Terraform's plan on each pull request, and apply it on merge.
6. **Stream files** once they pass about 100 MB.

## What the first version had, and why it went

The first version (commit `7f4be62`) took about 4,000 lines to load bronze: 1,994 of Python, 1,455 of tests and 553 of JSON. It worked, but every line is something to read, test and fix. The rebuild keeps every guarantee and its test:

| First version | Now | Why it went |
|---|---|---|
| A JSON Schema registry for the tables | `[sources.*]` in `pipeline.toml` | Bronze is all text, so column names are all it needs |
| One class per ingest step (reader, matcher, budget, stage) | Plain functions in `ingest.py` | The tests only ever needed the whole stage |
| Seven error classes | One `PipelineError` | Nothing caught them separately |
| A `Lake` interface with one implementation | Small functions in `lake.py` | The cloud demo mounts the bucket as a folder, so plain paths work |
| A saved DuckDB file | Views made in memory | Not byte-identical, and it locks out the dashboard |
| A config search across several places | One `--config` file | One settings file is enough |

They come back when there's a reason: see "What's next" in [the README](../README.md#whats-next).
