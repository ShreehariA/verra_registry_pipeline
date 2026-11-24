# The cloud demo on Google Cloud: every resource it needs (page 2 of docs/architecture/verra-pipeline-as-built.drawio).
# deploy/gcp.sh runs it: `up` is terraform apply and `down` is terraform destroy. Terraform records what it made in
# deploy/terraform.tfstate (git-ignored): keep that file until `down`.

terraform {
  required_version = "~> 1.15"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 7.0"
    }
  }
}

variable "project" {
  description = "The Google Cloud project to use. There is no default: the gcloud default project is never used."
  type        = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project))
    error_message = "Set project to a Google Cloud project ID, such as my-project-123."
  }
}

variable "region" {
  description = "Where everything is created."
  type        = string
  default     = "us-central1"
}

provider "google" {
  project = var.project
  region  = var.region
  # API calls count against this project, never the quota project saved with a gcloud login
  billing_project       = var.project
  user_project_override = true
}

locals {
  root = abspath("${path.module}/..")
  # The files the Dockerfile copies (keep in step with its COPY lines), less the cache files git ignores
  sources = [
    for file in setunion(
      fileset(local.root, "{Dockerfile,pyproject.toml,uv.lock,README.md,pipeline.toml}"),
      fileset(local.root, "{.streamlit,src,sql,dashboard}/**"),
    ) : file if !strcontains(file, "__pycache__") && !endswith(file, ".DS_Store")
  ]
  # The image's tag is a checksum of those files, so a new image is built exactly when one of them changes
  tag   = substr(sha256(join("\n", [for file in local.sources : "${file} ${filesha256("${local.root}/${file}")}"])), 0, 12)
  image = "${var.region}-docker.pkg.dev/${var.project}/${google_artifact_registry_repository.verra.repository_id}/verra:${local.tag}"
  # Two service accounts, each with one role on the bucket and nothing else
  roles = {
    verra-pipeline  = "roles/storage.objectAdmin"
    verra-dashboard = "roles/storage.objectViewer"
  }
  # The bucket is mounted at /data. implicit-dirs: folders made by `gcloud storage cp` show up; uid/gid: the image's user
  mount_options = ["implicit-dirs", "uid=1000", "gid=1000"]
}

resource "google_project_service" "apis" {
  for_each           = toset(["run", "cloudbuild", "artifactregistry", "storage", "iam"])
  service            = "${each.key}.googleapis.com"
  disable_on_destroy = false # other things in the project may need them
}

# One bucket for landing/ and lake/
resource "google_storage_bucket" "verra" {
  name                        = "${var.project}-verra"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced" # the dashboard is public; the files behind it never are
  force_destroy               = true       # `down` deletes the files in it too
  depends_on                  = [google_project_service.apis]
}

resource "google_artifact_registry_repository" "verra" {
  repository_id = "verra"
  location      = var.region
  format        = "DOCKER"
  depends_on    = [google_project_service.apis]
}

# Cloud Build builds the image from the repository folder, so this machine needs no Docker. A new tag builds again.
resource "terraform_data" "image" {
  triggers_replace = local.image
  provisioner "local-exec" {
    working_dir = local.root
    # the source archive goes into our bucket, so `down` removes it too
    command = "gcloud builds submit --tag ${local.image} --gcs-source-staging-dir gs://${google_storage_bucket.verra.name}/cloud-build --region ${var.region} --project ${var.project} ."
  }
}

resource "google_service_account" "verra" {
  for_each     = local.roles
  account_id   = each.key
  display_name = "Verra demo: ${each.key}"
  depends_on   = [google_project_service.apis]
}

resource "google_storage_bucket_iam_member" "verra" {
  for_each = local.roles
  bucket   = google_storage_bucket.verra.name
  role     = each.value
  member   = google_service_account.verra[each.key].member
}

resource "google_cloud_run_v2_job" "pipeline" {
  name                = "verra-pipeline"
  location            = var.region
  deletion_protection = false # so `down` can delete it
  template {
    template {
      service_account = google_service_account.verra["verra-pipeline"].email
      timeout         = "600s"
      max_retries     = 0
      containers {
        image   = local.image
        command = ["verra"]
        args    = ["build", "--landing", "/data/landing", "--lake", "/data/lake"]
        resources {
          limits = { cpu = "1", memory = "1Gi" }
        }
        volume_mounts {
          name       = "data"
          mount_path = "/data"
        }
      }
      volumes {
        name = "data"
        gcs {
          bucket        = google_storage_bucket.verra.name
          mount_options = local.mount_options
        }
      }
    }
  }
  # the image must exist, and the service account must be able to open the bucket
  depends_on = [terraform_data.image, google_storage_bucket_iam_member.verra]
}

resource "google_cloud_run_v2_service" "dashboard" {
  name                 = "verra-dashboard"
  location             = var.region
  deletion_protection  = false
  invoker_iam_disabled = true # public: anyone with the URL can open it
  template {
    service_account = google_service_account.verra["verra-dashboard"].email
    scaling {
      max_instance_count = 2 # and none while nobody is looking
    }
    containers {
      image = local.image
      resources {
        limits = { cpu = "1", memory = "1Gi" }
      }
      volume_mounts {
        name       = "data"
        mount_path = "/data"
      }
    }
    volumes {
      name = "data"
      gcs {
        bucket        = google_storage_bucket.verra.name
        read_only     = true
        mount_options = local.mount_options
      }
    }
  }
  depends_on = [terraform_data.image, google_storage_bucket_iam_member.verra]
}

output "url" {
  description = "The dashboard's address"
  value       = google_cloud_run_v2_service.dashboard.uri
}
