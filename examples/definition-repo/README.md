# Example definition repository

This tree is a **minimal fixture** for the framework JSON Schemas (`schemas/*.schema.json`, draft 2020-12). It is not a live dataset catalog.

Layout:

- `repo.yml` — repository metadata (`name`, `default_schema`, optional `dependencies`, …).
- `datasets/*.yml` — one file per dataset (`name`, `tables[]`, optional schedules, …).
- `models/` — optional **dbt** project (`dbt_project.yml`, `models/*.sql`, `dbt_profile/profiles.yml`). See **dbt** in `docs/local-development.md`.

Validate locally (after `pip install -e ".[dev]"` or `pip install PyYAML jsonschema`):

```bash
python scripts/validate_definitions.py --repo examples/definition-repo
```

dbt (optional): with `pip install ".[dev]"` or `".[compose]"` (installs `dbt-core`, `dbt-postgres`, `dagster-dbt`):

```bash
export DBT_PROFILES_DIR="$PWD/examples/definition-repo/models/dbt_profile"
export DBT_TARGET_SCHEMA=ex_housing   # must match definitions[].schema for this example
dbt parse --project-dir examples/definition-repo/models --target dev
# After loader materialized `sample_csv.rows` into Postgres:
dbt run --project-dir examples/definition-repo/models --target dev
```

Definition repositories such as `nycdb2` are **separate works**: they ship YAML, SQL, and markdown only, and are consumed by the framework at deploy time—not forked copies of the framework.
