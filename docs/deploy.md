# The cloud demo

The same image that runs locally runs on Google Cloud: a Cloud Run job builds the lake in a Cloud Storage bucket, and a public Cloud Run service serves the dashboard. Terraform (`deploy/main.tf`) creates and deletes every resource, and `deploy/gcp.sh` runs it.

![Infrastructure, as built](architecture/verra-pipeline-as-built-infra.png)

## What it creates

- **One Cloud Storage bucket,** `<project>-verra`, holding `landing/` and `lake/`. It can never be made public.
- **One image,** built by Cloud Build into Artifact Registry. Its tag is a checksum of the files it's built from, so `up` builds it again only when one of them changes.
- **A Cloud Run job, `verra-pipeline`,** that runs `verra build` with the bucket mounted at `/data`: 1 CPU, 1 GiB, at most 10 minutes, no retries.
- **A public Cloud Run service, `verra-dashboard`,** that reads the lake through a read-only mount. It scales to zero and runs at most 2 instances.
- **Two service accounts,** each with one role on that bucket only: the job's can read and write files, the dashboard's can only read.

## How the work is split

- **Terraform** describes what should exist. It keeps a record of what it made (`deploy/terraform.tfstate`), compares it with the description and with what's really there, and shows the difference as a plan. `apply` carries out the plan; `destroy` deletes everything in the record.
- **`deploy/gcp.sh`** is what you type. It refuses to start without a named project, runs Terraform for `up` and `down`, and does the one job that isn't infrastructure: `run` uploads a day's files and starts the pipeline.

## Deploying

You need `gcloud`, `terraform` and a Google Cloud project of your own, with billing on.

```bash
gcloud auth login                        # for gcloud: the image build, the upload, the job
gcloud auth application-default login    # for Terraform
export GCP_PROJECT=<your-project-id>

deploy/gcp.sh up --dry-run    # Terraform's plan: 14 resources to add, every name in your project
deploy/gcp.sh up              # create or update: Terraform shows the plan and waits for "yes"; prints the URL
deploy/gcp.sh run             # upload data/landing/*.csv, run the job, print the URL again
deploy/gcp.sh down            # delete everything up made, the bucket's files included, after the same "yes"
```

- The first `up` takes a few minutes, mostly for the image build.
- Until `run` has finished, the dashboard says that nothing has been built yet.
- Then the tiles must show issued 198,511,826 · retired 56,564,196 · cancelled 6,123,377 · available 135,824,253, the same as `make build` locally.
- Run `up` again after a code change: only the image, the job and the dashboard change.
- `GCP_REGION` picks another region; the default is us-central1.

## Safety

- **The gcloud default project is never used.** The script stops without `GCP_PROJECT`. Terraform's `project` setting has no default, and it must look like a project ID. Every gcloud command names `--project`.
- **Nothing changes without a "yes".** Terraform shows its plan first, and anything but `yes` changes nothing.
- **Dry runs change nothing.** With `--dry-run`, `up` and `down` only show Terraform's plan, and `run` prints its commands. A test checks this with fake `terraform` and `gcloud` commands that record every call.
- **Least privilege.** Each service account has one role, on the one bucket. The dashboard's mount is read-only, so even a bug in it can't damage the lake.
- **`down` deletes everything `up` created,** the bucket's files and Cloud Build's uploaded source included. It leaves the APIs that `up` turned on, which cost nothing. Keep `deploy/terraform.tfstate` until `down`: without it, Terraform forgets what it made.

CI checks the Terraform's format and validity on every push, offline.

## If something fails

| Symptom | Likely cause | What to do |
|---|---|---|
| Terraform can't find credentials | No application-default sign-in | `gcloud auth application-default login`, then `up` again |
| `up` stops with "API has not been used" or "service account does not exist" | A just-enabled API, or a new account, takes a minute to work everywhere | Wait a minute and run `up` again; Terraform carries on from where it stopped |
| The build can't push the image | Cloud Build's service account lacks permission | Grant it `roles/artifactregistry.writer` in the project, then `up` again: the failed build is retried |
| The job fails writing `lake/` | DuckDB's writes or renames through the bucket mount | Build in `/tmp/lake` and copy it to the bucket at the end: a small change to the job's command |
| The job says the landing folder is empty | Folders made by `gcloud storage cp` aren't visible in the mount | Check that the mount has `implicit-dirs` (`gcloud run jobs describe verra-pipeline`) |
| The URL returns 403 | The organisation forbids public services | `gcloud run services proxy verra-dashboard --region us-central1 --project $GCP_PROJECT`, then open http://localhost:8080 |

## Not yet proved

Nothing has been deployed yet, so these are untested:
- that DuckDB can write through the bucket mount;
- that files uploaded with `gcloud storage cp` show up in the mount;
- that the organisation allows public services;
- that Cloud Build's service account can push the image;
- that the first `up` runs through in one go.

The full production design (Eventarc, Workflows, a run catalog, BigQuery, Terraform's record kept in a bucket), and what the demo leaves out of it, is in [the architecture](architecture.md).
