# Decisions, alternatives and limits

[The README](../README.md#decisions-and-the-alternatives-rejected) lists the main decisions. This page gives the reasons, what happens when things change, and the shortcuts taken on purpose.

## Why it's small

The brief asks for a few hours of work. A first version (commit `7f4be62`) took about 4,000 lines just to load bronze. The rebuild does the whole pipeline in about 950: 600 lines of Python and 350 of SQL. It keeps every integrity rule and its test. [What went, and why](architecture.md#what-the-first-version-had-and-why-it-went).

## Tools

| Choice | Why | Rejected |
|---|---|---|
| DuckDB, inside the process | About 10 MB a day. It reads and writes Parquet, with nothing to run. | Spark: a cluster buys nothing at this size. The Parquet lake still works with Spark or BigQuery later. |
| Python's `csv` module to read, SQL to model | Exact control over quotes, line numbers and raw text | pandas: it guesses types, and loses the line numbers quarantine needs |
| Plain SQL files, run in order | About 350 lines of SQL | dbt: a second tool to learn and set up |
| Streamlit | Python, in the same image as the pipeline | Looker Studio: it needs a warehouse this volume doesn't |
| A SQL page in the dashboard, on a locked-down copy | Anyone can trace a number to its raw line ([how it's kept safe](dashboard.md#the-sql-page)) | A separate SQL tool: one more thing to host and secure |
| TOML settings | In the standard library, and allows comments | JSON table definitions checked by JSON Schema (the first version) |

## Storage

- **Bronze, silver, gold.** Bronze is what was delivered, silver is what we believe, and gold is what we report. A better cleaning rule rebuilds silver and gold from bronze.
- **Every day kept, in its own folder.** A re-run replaces only its own day.
- **Parquet files, not a saved DuckDB file.** A DuckDB file's bytes change on every write, and only one program can write it, so a build would fail while the dashboard is open.
- **Built in memory, then written.** A failed check writes nothing.

## The model

- **One fact table for all three kinds of event.** Balances are sums by kind. *Rejected:* three fact tables, or a table per entity (third normal form).
- **Flag, never drop.** A value that can't be read becomes NULL, and is counted. *Rejected:* filtering bad rows, which breaks the counts and hides problems.
- **Errors only when a number would be wrong.** *Rejected:* failing on every oddity, which would block every day over facts about history.
- **Owner names merged by a key** ([why it matters](data-analysis.md#owners-question-3)). *Rejected:* fuzzy matching, which is hard to explain and can merge two companies.
- **Each project's most common details.** *Rejected:* the first or last batch's, which depend on the file's order.

## Robustness

- **A bad record goes to quarantine; it doesn't stop the run.** One cut-off line in 23,284 shouldn't block a day, but it mustn't vanish either.
- **A reject budget, counted in lines,** stops the run when a few bad lines become a broken file.
- **Headers matched by name,** so a renamed column is a settings change, not a code change.

## The cloud demo

- **Terraform, run by a short script.** Terraform records what it made, so `down` deletes exactly that, and its plan shows every change first. *Rejected:* gcloud commands alone, where `down` must list everything by hand.
- **The image is built from Terraform,** because Cloud Run needs the image before it can create the job. Its tag is a checksum of the files it's built from, so it's only rebuilt when one of them changes.
- **One bucket, one image, scale to zero.** What it leaves out of the production design: [the architecture](architecture.md#the-demo-against-the-production-design).

## What if…

- **Verra renames a column?** The run stops and names it. One alias line in `pipeline.toml` fixes it.
- **Verra adds a column?** It's kept in bronze.
- **Verra removes a column?** A required one stops the run; an optional one loads empty.
- **Verra restates a day?** Build it again. The day's files are replaced, and the new checksums show the change.
- **The data grows 100 times?** That's about 1 GB a day: read files in batches (the `shortcut:` in `ingest.py`). At 1,000 times, serve gold from BigQuery.

## Known gaps and shortcuts

None of these changes today's numbers.

- **Files are read whole into memory:** about 300 MB at peak for 9.4 MB of files. Stream them past about 100 MB a file.
- **One build at a time.** Two at once would write the same temporary files. Add a lock if builds ever run in parallel.
- **A restated day replaces the old one,** so the old checksum isn't kept.
- **A file mixing UTF-8 and Windows-1252** is read whole as Windows-1252, which garbles its accents. It's reported.
- **File names must be `<prefix>_<YYYY-MM-DD>.csv`,** with a prefix of letters and digits.
- **New columns aren't flagged,** only kept.
- **The dashboard and `verra query` show the newest day.** Older days stay on disk.
- **Each query on the SQL page copies the snapshot** into memory: 50 ms and 44 MB today. Queries take turns, so there's one copy at a time.
- **A multi-year vintage counts in its first year** on charts by year.
- **Not done yet:** names in the retirement details, splitting multi-value fields, and ISO country codes ([why](data-analysis.md#left-alone-on-purpose)).
- **Parquet bytes can differ between CPU types.** Google Cloud's build holds the same data, row for row, but DuckDB compressed some pages differently there ([run log](run-log.md)).
