# opendata-etl

This site documents the **opendata-etl** framework: Postgres-targeted ETL, dbt-derived models, Dagster orchestration, and read-only APIs driven by external **definition repositories**.

## What you will find here

- **Local development** — Docker Compose, environment variables, and day-to-day workflow.
- **Definition repo docs** — Narrative markdown copied from each loaded definition repository at build time, under one path per repo.
- **Generated reference** — Stubs from dbt `manifest.json` (models, sources, columns when present) and from dataset YAML via the same asset skeleton metadata the pipeline uses for Dagster.

Canonical product planning lives outside this repository (master plan at `_planning/opendata-etl_master_plan.plan.md` and architecture at `_planning/etl_pipeline_tech_stack.plan.md` in your workspace). In-repo developer notes focus on how to run and extend the framework.

## Building these docs locally

From the repository root, install documentation dependencies, generate aggregated pages, then build:

```bash
pip install ".[dev,docs]"
python scripts/aggregate_docs.py --mode embedded
python scripts/gen_docs.py --mode embedded
mkdocs build --strict
```

The `embedded` mode uses the checked-in `examples/definition-repo` tree (no git clone). For manifests that use real git URLs, use `--mode clone` with `--deployment` and `--work-dir` (see `python scripts/aggregate_docs.py --help`).
