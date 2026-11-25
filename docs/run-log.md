# Run log

Real runs, and how long each step took. Newest first.

## 25 Nov 2026: first deploy to Google Cloud

Project `verra-demo-7342`, region us-central1, from commit `ca1dbe2`. Live at https://verra-dashboard-480199239724.us-central1.run.app; the older-style address, https://verra-dashboard-k2k4mrcqsa-uc.a.run.app, reaches the same service.

| Step | Took | What happened |
|---|---|---|
| `deploy/gcp.sh up`, first try | under a minute | Stopped with a 403. Terraform's Google provider looks the project up through the Cloud Resource Manager API, which a new project doesn't have on. `gcp.sh` now turns it on first. |
| `deploy/gcp.sh up` | about 2.5 min | 13 resources created. Building the image on Cloud Build took 1 min 31 s of it, and the dashboard service 32 s. |
| `deploy/gcp.sh run`: the upload | about 1.5 s | 3 files, 8.9 MiB |
| `deploy/gcp.sh run`: the job | 49 s | 34 s getting a machine and starting the container, then 13 s for the build itself, on 1 CPU through the bucket mount. Same report and totals as on a laptop. |
| A new dashboard instance | about 5 s | From starting to answering on its port: 4.8 s and 5.7 s, the two times it happened |
| The first visit after a quiet spell | about 8 s | A new instance starts, then the page loads the lake |
| Any later page | about 1 s | Each of the 7 pages showed its title in 1–2 s |

**Checked afterwards:**
- every page shows the same numbers as locally, with no error;
- a second `up --dry-run` plans no changes;
- nothing private is reachable from the internet: the bucket's files answer 403 and the image registry 401;
- the SQL page's guardrails hold on the live server: reading `/etc/passwd`, writing a file, installing an extension, switching file access back on and a query that never ends were all refused;
- the cloud lake holds the same data as a local build: every table, row for row, in the same order. The manifest is byte-identical. The Parquet files differ by a few bytes each, because the same DuckDB build compressed some pages differently there; the encodings and the sizes before compression are identical. The likeliest cause is the CPU type: x86 in Google Cloud, Arm on the Mac.
- **found, and fixed by a second `up` the same day** (dashboard revision `00002`): Cloud Run's default 300 s request timeout cut each viewer's connection every 5 minutes (a live watch saw it at 303 s, then Streamlit reconnect). The dashboard now allows an hour, and a reconnecting page goes back to the same copy. And setting CPU limits had quietly made Cloud Run bill CPU for each instance's whole life; `cpu_idle = true` bills it only while a request is open;
- the job's log shows `BufferedWriteHandler.OutOfOrderError` for 5 files. The bucket mount uploads a file as it's written, and DuckDB wrote some bytes out of order, so the mount fell back to its slower way of writing those files. They're complete: the comparison above covers them.

## Local runs

A MacBook Pro (Apple M4 Pro), with the 2026-11-17 files:

| Command | Took |
|---|---|
| `make build` | 0.8 s |
| `make check`: lint, types and 70 tests | 17 s |
| `make analysis` | 4.5 s |
| A typical query on the SQL page | under 3 ms |
