# opendata-etl

Framework repository for the **opendata-etl** project: an **AGPLv3** toolkit for Postgres-targeted ETL, derived jobs, read-only APIs, and docs aggregation. Dataset behavior is driven by **external definition repositories** loaded at deployment time.

## What this repo is

- The only repository in the multi-repo workspace that contains **executable framework code** for this stack.
- Licensed under the **GNU Affero General Public License v3.0** (see `LICENSE`). SPDX short identifier: **AGPL-3.0** (Python sources in this repo use `# SPDX-License-Identifier: AGPL-3.0-only` where applicable).
- Distributed primarily as a **Docker image** and Python package metadata (`pyproject.toml`); deployments **consume** released artifacts rather than forking the framework to ship city-specific logic.

## What this repo is not

- **Not** a definition repository. City- or domain-specific datasets, dbt models, API endpoint specs, and narrative docs live in repos such as **`nycdb2`**. Those repos are **separate creative works**: shipping YAML/SQL/markdown that the framework reads does **not**, by itself, make them derivatives of this framework for licensing purposes. They may use their own license at the maintainer's discretion.
- **Not** a place for deployment secrets or environment-specific wiring. Deployment configuration (for example `definitions.yml`, environment files, Terraform) lives in directories such as **`opendata-etl-deployment`**.
- **Not** a store for protected source credentials. Access to data sources is declared by **named references** in configuration; values are resolved at runtime from the environment, cloud secret stores, or IAM—**never** committed to git.

## Local development and definition repos

Local and CI environments should use **pinned git revisions** for each definition repository (commit SHA or immutable tag). For offline or rapid iteration, git URLs may use the **`file://`** scheme to point at a local clone. The loader is `pipeline.definitions.load_definitions` (see **Step 3** in the master plan).

**Docker Compose** (PostGIS, MinIO, Dagster shell, FastAPI shell): copy `.env.example` to `.env`, then from the repo root run `docker compose config` and `docker compose up --build`. Detailed workflow, env vars, and health-check notes: [docs/local-development.md](docs/local-development.md).

## Layout (skeleton through Step 4)

| Path | Role |
|------|------|
| `pipeline/` | Definitions loader, validation, minimal `dagster_defs` shell for Compose. |
| `api/` | FastAPI app shell (`api/app.py`) with `GET /healthz`. |
| `schemas/` | JSON Schema contracts for YAML (`repo.yml`, datasets, API endpoints, definitions manifest). |
| `scripts/` | CLI and validation (`scripts/validate_definitions.py`). |
| `docs/` | MkDocs Material site (`mkdocs.yml`); run `aggregate_docs.py` + `gen_docs.py` before `mkdocs build`. |
| `examples/` | Sample definition repo tree and `definitions*.yml` manifests. |
| `docker-compose.yml` | Local runtime: `postgres`, `minio`, `dagster`, `api`. |
| `infra/aws/` | Future Terraform / AWS reference (Step 17). |
| `.github/workflows/` | CI: Python tests, fixture validation, `docker compose config` (no image pull). |

## Python extras

- **`pip install -e ".[dev]"`** — local test and validation tools, including pytest and `dg`.
- **`pip install -e ".[docs]"`** — MkDocs and Material theme (aggregated documentation site).
- **`pip install ".[compose]"`** — Dagster webserver, FastAPI, uvicorn, plus PyYAML/jsonschema (matches the application image install).

CI installs **`pip install -e ".[dev,docs]"`** so tests, definition validation, `dg check`, dbt parsing, and MkDocs all use the same packaged extras.

## Source-of-truth documents

Planning files live in the shared **`_planning/`** folder of the multi-repo workspace (not versioned inside this repo):

- **Master plan** (agent-led steps and handoffs): `/Users/maxwell/repos/_planning/opendata-etl_master_plan.plan.md`
- **Architecture plan** (decisions and rationale): `/Users/maxwell/repos/_planning/etl_pipeline_tech_stack.plan.md`

## Status

Follow the [master plan](docs/index.md) in `_planning/` for current milestones. The repo includes Docker Compose, the definitions loader, extract/load, dbt and API factories, monitoring, and an **MkDocs Material** documentation build (`mkdocs.yml`, `scripts/aggregate_docs.py`, `scripts/gen_docs.py`) with optional GitHub Pages deployment.

## Contributing

See `CONTRIBUTING.md` and `CODE_OF_CONDUCT.md`.
