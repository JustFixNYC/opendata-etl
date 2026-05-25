# Deployment Repositories

`opendata-etl` uses three repository layers:

- **Framework repo:** executable code, schemas, tests, docs, reference Docker Compose, and reference Terraform modules.
- **Definition repos:** dataset YAML, dbt models, API endpoint YAML, docs, and optional derived Python code.
- **Deployment repos:** environment-specific manifests, `.env` examples, Terraform variables/state, and runtime compose files.

The framework image does not bake in definition repos. A deployment manifest points at definition repos by git URL and pinned ref, and the runtime clones them into `OPENDATA_DEFINITIONS_WORK_DIR`.

## What Belongs In A Deployment Repo

Store these files in the deployment repo, not in the framework repo:

- `definitions.local.yml`, `definitions.poc.yml`, and `definitions.prod.yml`
- `.env.example`, with real `.env` ignored
- `docker-compose.yml` for `profile: lite`, using a pinned framework image
- `runtime/orchestrator-compose.yml` and `runtime/api-compose.yml` for `profile: standard`
- `infra/terraform.tfvars.example`, with real `terraform.tfvars` and state ignored

Use `examples/deployment-repo/` as the starting template.

## Framework Reference Vs Operator Apply

`infra/aws/` in this repo is reference IaC. Operators should apply Terraform from their deployment repo, with a module source pinned to a framework release tag, for example:

```hcl
module "opendata_etl_aws" {
  source = "github.com/example-org/opendata-etl//infra/aws?ref=v0.1.0"
}
```

This keeps public framework releases reproducible while allowing each operator to keep CIDRs, tfvars, state, SSM paths, and image pins under their own controls.

## Image Pinning

Contributor Compose in the framework repo uses `build: .` because it is for hacking on framework code. Deployment repos should use immutable or release-like image tags:

```yaml
services:
  dagster:
    image: ghcr.io/example-org/opendata-etl:v0.1.0
```

Use the same image pin for lite Compose, standard orchestrator, and standard API unless you are intentionally canarying a release.
