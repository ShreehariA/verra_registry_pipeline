# How to run it: the operating procedure

Step by step, for anyone: set it up, build the data, look at the answers, run it on a new snapshot, test it, deploy the cloud demo, and change it safely. Every step gives the commands, what you should see, and what to do if you don't.

Run every command from the repository folder. `make` on its own lists them all.

**Contents**
1. [What you need](#1-what-you-need)
2. [Set up, once](#2-set-up-once)
3. [Build the data](#3-build-the-data)
4. [Look at the answers](#4-look-at-the-answers)
5. [Run it on another snapshot](#5-run-it-on-another-snapshot)
6. [Test it](#6-test-it)
7. [Re-run the data analysis](#7-re-run-the-data-analysis)
8. [Run it in Docker](#8-run-it-in-docker)
9. [Deploy the cloud demo](#9-deploy-the-cloud-demo)
10. [Change something](#10-change-something)
11. [Clean up](#11-clean-up)
12. [When something goes wrong](#12-when-something-goes-wrong)

## 1. What you need

| For | You need |
|---|---|
| Everything local | [uv](https://docs.astral.sh/uv/) and `make`. uv installs Python 3.13 and the locked packages itself. |
| Docker (optional) | Docker, instead of uv |
| The cloud demo (optional) | `gcloud`, `terraform` 1.15, and a Google Cloud project of your own, with billing on |

## 2. Set up, once

```bash
make setup                 # creates .venv with the exact package versions in uv.lock
uv run verra --help        # check: prints "usage: verra [-h] [--config CONFIG] {build,query}"
```

## 3. Build the data

```bash
make build                 # the one command: raw files to bronze, silver and gold, behind the quality gate
```

It takes about a second. **You should see:**

```
Snapshot 2026-11-17 from data/landing
...
Quality gate passed: all 6 error checks are clean
  warning: events with no readable date: 19 row(s), 209,992 credits
  ...
Credits: issued 198,511,826 · retired 56,564,196 · cancelled 6,123,377 · available 135,824,253
```

**Check three things in the report:**
1. **The date on the first line** is the snapshot you meant to build. A newer date skipped for a missing file is listed under Findings, and a `Note:` at the end means the lake holds a newer snapshot than this one ([section 5](#5-run-it-on-another-snapshot)).
2. **"Quality gate passed".** If a check fails, the build stops with one sentence, and nothing is written ([section 12](#12-when-something-goes-wrong)).
3. **The warnings** are facts about Verra's data. Today there are four; a new one deserves a look.

Running `make build` again gives byte-identical files. The raw files in `data/landing` are only ever read.

## 4. Look at the answers

**The dashboard:**

```bash
make dashboard             # then open http://localhost:8501; Ctrl+C stops it
```

The overview should show **198.5M credits issued**, split into 28.5% retired, 3.1% cancelled and 68.4% available. Each page has its own address (`/projects`, `/vintages`, `/retirers`, `/over_time`, `/data_quality`, `/sql`). What each page shows: [the dashboard](dashboard.md).

**SQL from the terminal,** on the newest finished snapshot:

```bash
make query SQL="select count(*) as projects from gold.dim_project"                 # 250
make query SQL="select * from gold.mart_project_balance order by issued desc limit 5"
make query SQL="select * from gold.quality_results where not passed"               # today's 4 warnings
```

Or type the same SQL into the dashboard's SQL page. Which table answers what: [the data model](data-model.md).

## 5. Run it on another snapshot

Verra publishes the three files every day. Each one holds the full history, so each day is built on its own.

```bash
cp ~/Downloads/Verra*_2026-11-24.csv data/landing/    # the three files, with the same names and one date
make clean build SNAPSHOT=2026-11-24                  # an empty lake, then exactly that date
```

**Why name the date:** without `SNAPSHOT`, the build takes the newest date that has all three files. If yours is older than ours (2026-11-17), that would be ours.

**Why `make clean` first:** every snapshot built stays in `lake/`, and the dashboard and `make query` always show the **newest** one. Built into a lake that already holds a newer date, an older snapshot would be written but not shown, and the report would end with a `Note:` saying so. Starting from an empty lake shows exactly the snapshot you built.

**Other ways, for one run:**

```bash
uv run verra build --landing /path/to/files           # files from another folder
uv run verra build --lake /tmp/verra-lake             # write somewhere else
```

**Check:** the first line of the report names the date that was built. In a daily run without `SNAPSHOT`, a newer date that's missing a file is skipped, and the report lists it under Findings with the file it lacks.

## 6. Test it

```bash
make check                                     # lint, format check, types, then all 70 tests: about 12 seconds
uv run pytest tests/test_dashboard.py -v       # one file, with each test's name
uv run pytest -k "gate"                        # only the tests whose names contain "gate"
```

**You should see** `70 passed`. GitHub Actions runs `make check` on every push. Two tests check the shipped 2026-11-17 snapshot. They're skipped when its files aren't in `data/landing`; the one for the analysis also when a newer snapshot is there. What each test file protects: [checks and tests](quality.md#the-tests).

**Does a test really protect a line?** Break the line on purpose, run the tests, and put it back. For example, delete the line in `src/verra_pipeline/lake.py` that removes a day's manifest before rebuilding it, and `test_a_rebuild_hides_its_day_until_every_file_is_written` fails.

## 7. Re-run the data analysis

The analysis behind [the data analysis](data-analysis.md) is in `analysis/`: one script per section of that page. Each reads the newest snapshot in `data/landing`, exactly as delivered, and writes nothing.

```bash
make analysis                                  # all of it, about 5 seconds
uv run python analysis/owners.py               # one section: owners, for question 3
```

**Look inside a snapshot yourself,** even one whose build the gate refused:

```bash
uv run python -i analysis/common.py            # loads the snapshot as delivered, then waits for you
>>> show("Undated retirements", "SELECT _source_line, retirement_qty FROM retirements WHERE retirement_date = ''")
```

## 8. Run it in Docker

The same image builds the lake and serves the dashboard. It needs neither uv nor Python.

```bash
docker build -t verra .
mkdir -p lake      # yours: on Linux, a folder Docker made for the mount would belong to root
docker run --rm --user "$(id -u):$(id -g)" -v "$PWD/data/landing:/data/landing:ro" -v "$PWD/lake:/data/lake" verra \
    verra build --landing /data/landing --lake /data/lake
docker run --rm -p 8080:8080 -v "$PWD/lake:/data/lake:ro" verra      # then open http://localhost:8080
```

**Check:** the build prints the same report as `make build`, and the dashboard shows the same 198.5M. Ctrl+C stops the dashboard's container.

## 9. Deploy the cloud demo

What it creates, and why: [the cloud demo](deploy.md). It costs a little while it runs, so take it down when you're done.

```bash
gcloud auth login                              # for gcloud: the image build, the upload, the job
gcloud auth application-default login          # for Terraform
export GCP_PROJECT=<your-project-id>           # never the gcloud default project

deploy/gcp.sh up --dry-run     # Terraform's plan: 14 resources to add, every name in your project; changes nothing
deploy/gcp.sh up               # create or update: shows the plan again and waits for "yes"; prints the URL
deploy/gcp.sh run              # upload data/landing/*.csv, build the lake in the cloud, print the URL
```

**Check:** open the URL. Until `run` has finished, the dashboard says nothing has been built yet. Then the overview must show the same 198.5M as locally.

- **After a code change:** run `up` again. Only the image, the job and the dashboard change.
- **A new snapshot:** `deploy/gcp.sh run <folder>` uploads that folder's CSV files and builds again. The bucket keeps every file uploaded, so there too the newest complete date is the one built and shown.
- **Take it down:** `deploy/gcp.sh down`. It shows what it will delete and waits for "yes". Keep `deploy/terraform.tfstate` until then: it's Terraform's record of what it made.

If a step fails, [the cloud demo's table of fixes](deploy.md#if-something-fails) lists the likely causes.

## 10. Change something

Whatever you change, finish with `make build` (read the report), then `make check`.

| You want to | Do this |
|---|---|
| Follow a column Verra renamed | Map the new header to the old name in `pipeline.toml`: `aliases = { quantity_retired = "retirement_qty" }` under that export. The build names the missing column until you do. |
| Change how a value is read or cleaned | Edit `sql/macros.sql` or the file in `sql/silver/`. The report's warnings and totals show the effect. |
| Change a table or an answer | Edit its file in `sql/gold/`. The quality gate checks that every mart still adds up to the fact table. |
| Add a quality check | Add one `UNION ALL SELECT 'warning', '<what it counts>', count(*), sum(quantity) FROM …` to `sql/checks.sql`. Use `'error'` only when a number would be wrong. Add a test to `tests/test_transform.py`. |
| Add a dashboard page | Create `dashboard/app_pages/<name>.py`, add its `st.Page` in `dashboard/app.py`, and add the name to `PAGES` in `tests/test_dashboard.py`, so the tests open it. |
| Accept a new reference number | When a change moves a number on purpose, update `tests/test_real_snapshot.py` and the docs that quote it (`grep -rn "<old number>" README.md docs`). |

## 11. Clean up

```bash
make clean                 # deletes lake/, everything the pipeline made; never data/landing
deploy/gcp.sh down         # if you deployed the cloud demo
```

## 12. When something goes wrong

Every error is one sentence, starting `error:`.

| What you see | Why | What to do |
|---|---|---|
| `make: uv: No such file or directory` | uv isn't installed | Install [uv](https://docs.astral.sh/uv/), then `make setup` |
| `error: no date has all 3 files in …/data/landing (…)` | A file is missing, or named differently | The three files need the same date: `VerraIssuances_<date>.csv`, `VerraRetirements_<date>.csv`, `VerraCancelled_<date>.csv` |
| `error: no files dated 2026-11-30 in …` | `--snapshot` asked for a date that isn't there | Pick a date that is in `data/landing` |
| `error: VerraIssuances_….csv: required columns are missing: units (it has …)` | Verra renamed or dropped a column | Find the new name in the list after "it has", and add an alias ([section 10](#10-change-something)) |
| `error: VerraRetirements_….csv: … lines (…%) could not be read; at most 1% is allowed` | The file is broken, for example by an unclosed quote | Get a fresh copy of the file. Raise `max_rejected_share` in `pipeline.toml` only if you know why the lines are broken. |
| `error: the quality gate failed, so nothing was written: <check>: <rows>` | A number would be wrong, so the snapshot wasn't published | The lake still holds the last good build. Find the rows with `uv run python -i analysis/common.py` ([section 7](#7-re-run-the-data-analysis)), fix the input or the rule, and build again |
| The dashboard says "nothing has been built in …/lake yet" | No build has finished | `make build` |
| The dashboard shows a different date from the one you built, and the report ended with a `Note:` | The lake holds a newer snapshot, and readers show the newest | `make clean build SNAPSHOT=<your date>` ([section 5](#5-run-it-on-another-snapshot)) |
| The dashboard isn't at http://localhost:8501, and the log says `Uvicorn server started on :::8502` | Another dashboard is still running on 8501, so this one took the next port | Open the port in that line, or stop the other dashboard first |
| `make check` stops at `ruff format --check` | A file isn't formatted | `uv run ruff format .`, then `make check` again |
