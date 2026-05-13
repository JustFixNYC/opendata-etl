# opendata-etl

Framework repository for the `opendata-etl` project.

This directory is reserved for the framework code that will be built per the master plan. Nothing is implemented yet.

## What this repo is

- The only repository in the project that will contain executable code.
- An AGPLv3 framework that loads dataset, dbt-model, API-endpoint, and docs definitions from one or more separate definition repositories at deployment time.
- Distributed as a Docker image; consumed (not forked) by deployments.

## What this repo is NOT

- It does not contain any city-specific datasets, models, or API endpoints. Those live in definition repositories such as `nycdb2`.
- It does not contain deployment configuration. That lives in deployment-specific directories such as `opendata-etl-deployment`.

## Source-of-truth documents

These live in the shared `_planning/` folder of the multi-repo workspace, not inside this repo:

- Master plan (agent-led implementation): `../_planning/opendata-etl_master_plan.plan.md`
- Architecture plan (decisions and rationale): `../_planning/etl_pipeline_tech_stack.plan.md`

## Status

Empty placeholder. The first scaffolding step (Step 0/1 of the master plan) has not run yet.
