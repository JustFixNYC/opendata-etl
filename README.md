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

Local and CI environments should use **pinned git revisions** for each definition repository (commit SHA or immutable tag). For offline or rapid iteration, git URLs may use the **`file://`** scheme to point at a local clone. Exact loader behavior is implemented in **Step 3** of the master plan; this repository already carries directory placeholders (`examples/definition-repo/`) for upcoming contract work.

## Layout (skeleton)

| Path | Role |
|------|------|
| `pipeline/` | Dagster assets, extraction, loading (placeholder packages). |
| `api/` | FastAPI application code (placeholder). |
| `schemas/` | JSON Schema stubs for YAML contracts (expanded in Step 2). |
| `scripts/` | CLI and validation scripts (stubs). |
| `docs/` | In-repo developer notes; canonical plans live under `_planning/`. |
| `infra/aws/` | Future Terraform / AWS reference (Step 17). |
| `.github/workflows/` | CI placeholders. |

## Source-of-truth documents

Planning files live in the shared **`_planning/`** folder of the multi-repo workspace (not versioned inside this repo):

- **Master plan** (agent-led steps and handoffs): `/Users/maxwell/repos/_planning/opendata-etl_master_plan.plan.md`
- **Architecture plan** (decisions and rationale): `/Users/maxwell/repos/_planning/etl_pipeline_tech_stack.plan.md`

## Status

**Step 1** of the master plan: repository skeleton, packaging metadata, license, Docker/Compose placeholders, and empty `pipeline` / `api` packages. Runtime services (Postgres, MinIO, Dagster, API) and the definitions loader are **not** implemented yet; follow the master plan for upcoming steps.

## Contributing

See `CONTRIBUTING.md` and `CODE_OF_CONDUCT.md`.
