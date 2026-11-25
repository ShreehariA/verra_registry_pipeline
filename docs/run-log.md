# Run log

Real runs, and how long each step took. Newest first.

## 25 Nov 2026: first deploy to Google Cloud

Project `verra-demo-7342`, region us-central1, from commit `ca1dbe2`. Live at https://verra-dashboard-k2k4mrcqsa-uc.a.run.app.

| Step | Took | What happened |
|---|---|---|
| `deploy/gcp.sh up`, first try | under a minute | Stopped with a 403. Terraform's Google provider looks the project up through the Cloud Resource Manager API, which a new project doesn't have on. `gcp.sh` now turns it on first. |
| `deploy/gcp.sh up` | about 2.5 min | 13 resources created. Building the image on Cloud Build took 1 min 31 s of it, and the dashboard service 32 s. |
| `deploy/gcp.sh run`: the upload | about 1.5 s | 3 files, 8.9 MiB |
| `deploy/gcp.sh run`: the job | 49 s | 34 s getting a machine and starting the container, then 13 s for the build itself, on 1 CPU through the bucket mount. Same report and totals as on a laptop. |
| A new dashboard instance | about 5 s | From starting to answering on its port |
| A dashboard page | about 1 s | Each of the 7 pages showed its title in 1–2 s |

**Checked afterwards:**
- every page shows the same numbers as locally, with no error;
- a second `up --dry-run` plans no changes;
- the cloud lake holds the same data as a local build: every table, row for row, in the same order. The manifest is byte-identical. The Parquet files differ by a few bytes each, because the same DuckDB build compressed some pages differently there; the encodings and the sizes before compression are identical. The likeliest cause is the CPU type: x86 in Google Cloud, Arm on the Mac.
- the job's log shows `BufferedWriteHandler.OutOfOrderError` for 5 files. The bucket mount uploads a file as it's written, and DuckDB wrote some bytes out of order, so the mount fell back to its slower way of writing those files. They're complete: the comparison above covers them.

## Local runs

A MacBook Pro (Apple M4 Pro), with the 2026-11-17 files:

| Command | Took |
|---|---|
| `make build` | 0.8 s |
| `make check`: lint, types and 70 tests | 17 s |
| `make analysis` | 4.5 s |
| A typical query on the SQL page | under 3 ms |
