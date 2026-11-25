# How to run it

Every task, step by step: the commands, what you should see, and what to do if you don't. Run each command from the repository folder. `make` on its own lists them all.

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

- **To run it:** [uv](https://docs.astral.sh/uv/) and `make`. uv installs Python 3.13 and the locked packages.
- **For Docker (optional):** Docker, instead of uv.
- **For the cloud demo (optional):** `gcloud`, `terraform` 1.15, and a Google Cloud project with billing on.

## 2. Set up, once

```bash
make setup             # install the exact package versions in uv.lock
uv run verra --help    # should print "usage: verra [-h] [--config CONFIG] {build,query}"
```

## 3. Build the data

```bash
make build
```

It takes about a second. You should see:

```
Snapshot 2026-11-17 from data/landing
...
Quality gate passed: all 6 error checks are clean
  warning: events with no readable date: 19 row(s), 209,992 credits
  ...
Credits: issued 198,511,826 · retired 56,564,196 · cancelled 6,123,377 · available 135,824,253
```

Check three things:
1. **The date on the first line** is the one you meant. A `Note:` at the end means the lake holds a newer day ([section 5](#5-run-it-on-another-snapshot)).
2. **"Quality gate passed".** If a check fails, the build stops with one sentence and writes nothing.
3. **The warnings** are facts about Verra's data. Today there are four, so a new one deserves a look.

Building again gives byte-identical files.

## 4. Look at the answers

```bash
make dashboard    # open http://localhost:8501; Ctrl+C stops it
```

The overview should show **198.5M credits issued**: 28.5% retired, 3.1% cancelled and 68.4% still available. What each page shows: [the dashboard](dashboard.md).

Or ask in SQL, here or on the dashboard's SQL page:

```bash
make query SQL="select count(*) as projects from gold.dim_project"     # 250
make query SQL="select * from gold.mart_project_balance order by issued desc limit 5"
make query SQL="select * from gold.quality_results where not passed"   # today's 4 warnings
```

Which table holds what: [the data model](data-model.md).

## 5. Run it on another snapshot

Each day's three files hold the full history, so each day is built on its own.

```bash
cp ~/Downloads/Verra*_2026-11-24.csv data/landing/   # the three files for one date
make clean build SNAPSHOT=2026-11-24                 # empty the lake, then build that date
```

- **`SNAPSHOT`** builds that date. Without it, the build takes the newest date that has all three files.
- **`make clean`** matters because the dashboard shows the newest day in `lake/`. If the lake holds a newer day than the one you built, the report ends with a `Note:` saying so.
- **For one run,** `uv run verra build --landing <folder>` reads other files, and `--lake <folder>` writes elsewhere.

## 6. Test it

```bash
make check                                 # lint, types and all 70 tests
uv run pytest tests/test_dashboard.py -v   # one file, each test by name
uv run pytest -k gate                      # only tests with "gate" in their name
```

You should see `70 passed`. GitHub Actions runs the same on every push to main and every pull request. Two tests use the 2026-11-17 files, and are skipped without them. The analysis test is also skipped when `data/landing` holds a newer snapshot, because the analysis reads the newest files: then you see `69 passed, 1 skipped`. What each test file covers: [checks and tests](quality.md#the-tests).

To see that a test really protects a line, break the line on purpose and run the tests. For example, delete the line in `src/verra_pipeline/lake.py` that removes a day's manifest before rebuilding it: `test_a_rebuild_hides_its_day_until_every_file_is_written` fails. Then put it back.

## 7. Re-run the data analysis

`analysis/` has one script per section of [the data analysis](data-analysis.md). They read the newest files in `data/landing`, as delivered, and write nothing.

```bash
make analysis                          # all of it, about 5 seconds
uv run python analysis/owners.py       # one section
uv run python -i analysis/common.py    # load the raw files, then ask your own questions:
>>> show("Undated retirements", "SELECT _source_line, retirement_qty FROM retirements WHERE retirement_date = ''")
```

The last one works even on files the quality gate refused.

## 8. Run it in Docker

One image builds the lake and serves the dashboard. You don't need uv or Python.

```bash
docker build -t verra .
mkdir -p lake    # make it yourself: on Linux, a folder Docker makes belongs to root
docker run --rm --user "$(id -u):$(id -g)" -v "$PWD/data/landing:/data/landing:ro" -v "$PWD/lake:/data/lake" verra \
    verra build --landing /data/landing --lake /data/lake
docker run --rm -p 8080:8080 -v "$PWD/lake:/data/lake:ro" verra    # open http://localhost:8080
```

The build prints the same report as `make build`.

## 9. Deploy the cloud demo

It costs a little while it's up, so take it down when you're done. What it creates: [the cloud demo](deploy.md).

```bash
gcloud auth login                        # sign in gcloud
gcloud auth application-default login    # sign in Terraform, with the same account
export GCP_PROJECT=<your-project-id>     # the default gcloud project is never used

deploy/gcp.sh up --dry-run   # show the plan (14 resources); changes nothing
deploy/gcp.sh up             # create it, after you type yes; prints the URL
deploy/gcp.sh run            # upload data/landing and build the lake in the cloud
```

Open the URL. The overview should show the same 198.5M as on your machine. Until `run` finishes, it says nothing has been built yet.

- **After a code change,** run `up` again.
- **For a new snapshot,** `deploy/gcp.sh run <folder>` uploads that folder's files and builds again.
- **To take it down,** `deploy/gcp.sh down`. Keep `deploy/terraform.tfstate` until then: it's Terraform's record of what it made.

If a step fails: [what to do](deploy.md#if-something-fails).

## 10. Change something

After any change, run `make build` and read the report, then `make check`.

| To | Do this |
|---|---|
| Follow a column Verra renamed | Add an alias under that file in `pipeline.toml`: `aliases = { quantity_retired = "retirement_qty" }` |
| Change how a value is cleaned | Edit `sql/macros.sql`, or the file in `sql/silver/` |
| Change a table or an answer | Edit its file in `sql/gold/` |
| Add a quality check | Add a line to `sql/checks.sql`, and a test to `tests/test_transform.py`. Make it an `'error'` only when a number would be wrong. |
| Add a dashboard page | Add `dashboard/app_pages/<name>.py`, its `st.Page` in `dashboard/app.py`, and its name to `PAGES` in `tests/test_dashboard.py` |
| Accept a new number on purpose | Update `tests/test_real_snapshot.py`, and the docs that quote it: `grep -rn "<old number>" README.md docs` |

## 11. Clean up

```bash
make clean            # delete lake/; data/landing is never touched
deploy/gcp.sh down    # if you deployed the cloud demo
```

## 12. When something goes wrong

Every error is one sentence that starts with `error:`.

| You see | What to do |
|---|---|
| `make: uv: No such file or directory` | Install [uv](https://docs.astral.sh/uv/), then `make setup` |
| `error: no date has all 3 files in …` | Give the three files the same date: `VerraIssuances_<date>.csv`, `VerraRetirements_<date>.csv`, `VerraCancelled_<date>.csv` |
| `error: no files dated 2026-11-30 in …` | `SNAPSHOT` names a date that isn't in `data/landing` |
| `error: …: required columns are missing: units (it has …)` | Verra renamed a column. Find its new name after "it has", and add an alias ([section 10](#10-change-something)). |
| `error: …: … lines (…%) could not be read; at most 1% is allowed` | The file is broken. Get a fresh copy. |
| `error: the quality gate failed, so nothing was written: …` | A number would be wrong, and the lake keeps the last good build. Look at the rows with `uv run python -i analysis/common.py` ([section 7](#7-re-run-the-data-analysis)). |
| The dashboard says "nothing has been built … yet" | Run `make build` |
| The dashboard shows another date, and the build ended with `Note:` | `make clean build SNAPSHOT=<your date>` |
| The dashboard isn't on port 8501, and its log names port 8502 | Another dashboard is using 8501. Open 8502, or stop the other one. |
| `make check` stops at `ruff format --check` | Run `uv run ruff format .`, then `make check` again |
