# opendata-etl

This site documents the **opendata-etl** framework: Postgres-targeted ETL, dbt-derived models, Dagster orchestration, and read-only APIs driven by external **definition repositories**.

## What you will find here

- **Local development** — Docker Compose, environment variables, and day-to-day workflow.
- **Deployment repositories** — how operators pin framework images, definition repos, runtime compose files, and Terraform variables.
- **Definition repo docs** — Narrative markdown copied from each loaded definition repository at build time, under one path per repo.
- **Generated reference** — Stubs from dbt `manifest.json` (models, sources, columns when present) and from dataset YAML via the same asset skeleton metadata the pipeline uses for Dagster.

In-repo developer notes focus on how to run, extend, release, and operate the framework. Environment-specific manifests and secrets belong in a deployment repo, not in this framework repo.

## Building these docs locally

From the repository root, install documentation dependencies, generate aggregated pages, then build:

```bash
pip install ".[dev,docs]"
python scripts/aggregate_docs.py --mode embedded
python scripts/gen_docs.py --mode embedded
mkdocs build --strict
```

Sidebar entries under **`generated/`** come from **`docs/.nav.yml`** (MkDocs **awesome-nav**). New definition repos appear automatically after you re-run the two scripts; if you change how paths are laid out under `docs/generated/`, update the globs there.

The `embedded` mode uses the checked-in `examples/definition-repo` tree (no git clone). For manifests that use real git URLs, use `--mode clone` with `--deployment` and `--work-dir` (see `python scripts/aggregate_docs.py --help`).
