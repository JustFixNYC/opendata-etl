# Deployment Repository Template

This tree shows what an operator-owned `opendata-etl` deployment repository can contain. It is intentionally separate from the framework repo:

- the framework repo publishes versioned code and reference IaC;
- definition repos publish dataset, dbt, API, docs, and optional derived-job definitions;
- a deployment repo pins both sides together with manifests, env files, Terraform variables, and per-host runtime files.

Copy this layout into a private or public repo for your environment. Keep real `.env`, `terraform.tfvars`, Terraform state, API keys, and cloud credentials out of git.

## Lite Profile

Use `docker-compose.yml` for a single-host deployment. It pulls a pinned framework image, mounts `./definitions.local.yml`, and runs Postgres, MinIO, Dagster, and the API without rebuilding framework code.

```bash
cp .env.example .env
docker compose config
docker compose up -d
```

## Standard Profile

Use `infra/` as a thin Terraform root that consumes the framework's AWS reference module by git ref. Use `runtime/` files on the EC2 hosts:

- `runtime/orchestrator-compose.yml` runs Dagster/batch and mounts Docker when derived jobs use `OPENDATA_DERIVED_RUNNER=docker`.
- `runtime/api-compose.yml` runs FastAPI only.
- `env.*.example` documents the env expected on each host. Live env files should come from SSM, your secret store, or a secure operator process.

Upload the runtime compose files and the selected manifest separately. Do not bake definition-repo YAML or deployment manifests into framework images.
