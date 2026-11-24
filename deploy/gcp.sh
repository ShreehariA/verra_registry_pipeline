#!/usr/bin/env bash
# The cloud demo on Google Cloud. Terraform (deploy/main.tf) creates, updates and deletes every resource; this script
# runs it with your project named, and loads the data.
#
#   GCP_PROJECT=<project> deploy/gcp.sh up   [--dry-run]   create or update everything; prints the dashboard's URL
#   GCP_PROJECT=<project> deploy/gcp.sh run  [DIR] [--dry-run]   upload DIR's CSVs (default data/landing), build
#   GCP_PROJECT=<project> deploy/gcp.sh down [--dry-run]   delete everything `up` created
#
# --dry-run changes nothing: `up` and `down` show Terraform's plan, and `run` prints its commands. Without it, Terraform
# shows the plan and waits for "yes". GCP_REGION defaults to us-central1.
set -euo pipefail

die() { echo "error: $*" >&2; exit 1; }

command=${1:-}
dry_run=false
positional=()
for arg in "${@:2}"; do
    if [[ $arg == --dry-run ]]; then dry_run=true; else positional+=("$arg"); fi
done
[[ -n ${GCP_PROJECT:-} ]] || die "set GCP_PROJECT to the Google Cloud project to use (the gcloud default is never used)"
[[ -f Dockerfile && -f pipeline.toml ]] || die "run this from the repository folder"

project=$GCP_PROJECT
region=${GCP_REGION:-us-central1}
export CLOUDSDK_CORE_PROJECT=$project  # belt and braces: every gcloud call, the image build too, also passes --project

terraform_deploy() {  # Terraform on deploy/main.tf, with the project and region named
    terraform -chdir=deploy init -input=false > /dev/null
    terraform -chdir=deploy "$@" -var "project=$project" -var "region=$region"
}

run() {  # print a command, then run it unless this is a dry run
    printf '+'; printf ' %q' "$@"; printf '\n'
    if ! $dry_run; then "$@"; fi
}

run_pipeline() {
    local folder=${1:-data/landing}
    compgen -G "$folder/*.csv" > /dev/null || die "no CSV files in $folder"
    run gcloud storage cp "$folder"/*.csv "gs://$project-verra/landing/" --project "$project"
    run gcloud run jobs execute verra-pipeline --region "$region" --project "$project" --wait
    run gcloud run services describe verra-dashboard --region "$region" --project "$project" --format 'value(status.url)'
}

case $command in
    up) if $dry_run; then terraform_deploy plan; else terraform_deploy apply; fi ;;
    run) run_pipeline ${positional[@]+"${positional[@]}"} ;;
    down) if $dry_run; then terraform_deploy plan -destroy; else terraform_deploy destroy; fi ;;
    *) sed -n '5,7p' "$0" | sed 's/^# //' >&2; exit 1 ;;
esac
