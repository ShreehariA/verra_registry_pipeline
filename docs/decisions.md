# Decisions, alternatives and limits

[The README](../README.md#decisions-and-the-alternatives-rejected) lists the main decisions in one table. This page gives the reasoning behind them, what happens when things change, and the shortcuts taken on purpose.

## Why it's small

The brief asks for a few hours of work, and says it doesn't expect a production system. A first version (git commit `7f4be62`) took about 4,000 lines just to load bronze. It was rebuilt at about 970 lines for the whole pipeline, raw files to gold: 610 of Python and 360 of SQL. The dashboard adds about 1,090 (seven pages and the SQL workspace), and the tests about 990. Every integrity rule and its test was kept. [The architecture](architecture.md#what-the-first-version-had-and-why-it-went) lists what went, and why.

## Tools

| Choice | Why | Rejected |
|---|---|---|
| DuckDB, inside the process | About 10 MB a day. It reads and writes Parquet natively, and handles far more than this on one machine. | Spark: a cluster's start-up time, cost and operations buy nothing at this size. The lake is Parquet in date folders, which Spark and BigQuery read too, so moving later doesn't change the data. |
| Python's `csv` module to read, SQL to model | Exact control over quotes, line numbers and raw text; SQL is easy to review. | pandas: `read_csv` guesses types and drops the line numbers and raw text that quarantine needs. |
| Plain SQL files, run in a fixed order | About 360 lines of SQL. | dbt: a second tool, with its own project and setup. |
| Streamlit | Python, so it reads the same views as `verra query`, and runs in the same image as the pipeline. | Looker Studio, in the production design: it would read gold from BigQuery, a warehouse this volume doesn't need. |
| A SQL page inside the dashboard, each query on its own locked-down copy of the tables | Anyone can check a number down to its raw line, or ask a question the pages don't answer, on the public page too ([how it's kept safe](dashboard.md#your-own-sql)). | A separate SQL tool beside the dashboard: one more thing to host and secure. Letting queries read the lake's folder: DuckDB would also let them write there. |
| TOML settings | In the standard library, allows comments, and matches `pyproject.toml`. | JSON table definitions checked against JSON Schema (the first version). |

## Storage

- **Medallion layers.** Bronze is what was delivered, never changed. Silver is what we believe: typed and flagged. Gold is what we report. When a cleaning rule improves, silver and gold are rebuilt from bronze, and nothing is fetched again.
- **Every snapshot kept, in date folders.** A re-run replaces exactly its own files, and earlier days stay on disk. *Rejected:* overwriting one set of tables each day.
- **Parquet files.** Columnar, compressed and typed, and every tool reads them.
- **No saved DuckDB file.** Its bytes change on every write, which breaks byte-identical output. Only one program can write it at a time, so a build would fail while the dashboard has it open. Making the views in memory takes milliseconds.
- **Everything built in memory, then written.** A failed check writes nothing. *Rejected:* writing each layer as it's made.

## The model

- **One fact table for all three kinds of event.** Balances are sums by event type, and the gate compares one table with silver. *Rejected:* three fact tables, or the earlier design's third-normal-form model, with a table per entity.
- **Flag, never drop.** A value that can't be read becomes NULL and is counted. *Rejected:* filtering bad rows in silver, which breaks the bronze-to-silver count and hides problems.
- **Errors only when a number would be wrong.** Undated rows or missing owners are facts about Verra's data, not reasons to publish nothing. *Rejected:* failing on every oddity, which would block every day over facts about history.
- **Owner names merged by a key.** The answer to question 3 depends on it ([data analysis](data-analysis.md#owners-question-3)). *Rejected:* fuzzy matching: it's hard to explain, and it can merge two different companies.
- **Each project's most common details.** Methodology and country can change between batches, and each batch keeps its own in silver. *Rejected:* the first or the last batch's details, which depend on the order of the file.

## Robustness

- **Quarantine, not failure, for a bad record.** One cut-off line in 23,284 shouldn't block a day's data, but it mustn't vanish either. Quarantine keeps the reason and the exact text.
- **A reject budget, counted in lines.** It stops the run when "a few bad lines" becomes "a broken file". It counts lines because one stray quote can swallow many lines into a single record.
- **Headers matched by name, through aliases.** A renamed or reordered column is a settings change, not a code change.

## The cloud demo

- **Terraform, run by a short script.** Terraform keeps a record of what it made. So `down` deletes exactly that, `up` changes only what differs, and its plan shows every change before it happens. The script refuses to start without a named project, and runs the pipeline itself: it uploads the files and starts the job, which is operating the system rather than building it. *Rejected:* gcloud commands alone, where `down` must list by hand everything `up` made.
- **The image is built from Terraform.** Cloud Run needs the image before it can create the job and the dashboard, and the image needs the registry, which Terraform creates. The tag is a checksum of the image's files, so the build runs only when the code changed. *Rejected:* two Terraform runs, the first limited to the registry; or a placeholder image that gcloud swaps later, leaving two tools changing the same service.
- **One bucket, one image, scale to zero.** What the demo leaves out of the production design, and when to add each piece, is in [the architecture](architecture.md#the-demo-against-the-production-design).

## What if…

- **Verra renames a column?** The run stops and names the missing column. One alias line in `pipeline.toml` fixes it.
- **Verra adds a column?** It's kept in bronze and listed in the manifest.
- **Verra removes a column?** A required one stops the run. An optional one is loaded empty, with a finding.
- **Verra restates a day?** Build it again with `--snapshot`. The day's files are replaced, and the new checksums show the change.
- **The data grows 100 times?** That's about 1 GB a day: read each file in batches instead of whole (the `shortcut:` comment in `ingest.py`). DuckDB is still fine. At 1,000 times, serve gold from BigQuery, as in the production design; the Parquet lake stays.

## Known gaps and shortcuts

None of these changes today's numbers. Each is a deliberate shortcut, or a small fix for later.

- **Files are read whole into memory.** The peak is 272 MB for 9.4 MB of files. Stream them past about 100 MB a file.
- **One build at a time.** Two builds at once would write the same temporary file names. That's fine for one scheduled job; add a lock if builds ever run in parallel.
- **A restated day replaces the earlier version,** so the earlier checksum isn't kept. The production design's run catalog keeps that history.
- **`verra query` reads the lake named in the settings.** Use `--config` with a copy to read another.
- **A file that mixes UTF-8 and Windows-1252** is decoded whole as Windows-1252, which garbles its UTF-8 accents. It's reported; decoding line by line would fix it.
- **File names:** prefixes must be letters and digits, and the extension exactly `.csv`.
- **New columns aren't flagged.** They're kept in bronze and listed in the manifest, but there's no finding for them.
- **The views show the newest finished day.** Earlier days stay on disk and can be read by path.
- **Each query on the SQL page copies the whole snapshot** into memory: 50 ms and 44 MB today. Past a few hundred MB, open a read-only DuckDB file of the snapshot instead.
- **A multi-year vintage counts in its first year** on charts by year.
- **Names written in Retirement Reason Details aren't used,** multi-value fields aren't split, and countries aren't ISO codes ([data analysis](data-analysis.md#left-alone-on-purpose)).
- **The cloud demo hasn't been deployed yet,** so writes through the bucket mount, the public URL and Cloud Build's permissions are unproven ([the cloud demo](deploy.md#not-yet-proved)).
