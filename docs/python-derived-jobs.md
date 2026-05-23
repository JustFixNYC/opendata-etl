# Python derived jobs

Definition repositories can ship **Python derived jobs**: YAML in `derived_jobs/` plus code under `python/derived/`. The framework runs the job, validates CSV outputs, and loads tables with the same atomic swap as datasets.

## Layout

```text
definition-repo/
├── repo.yml                 # derived_python: true
├── derived_jobs/
│   └── my_job.yml
└── python/derived/
    └── my_job.py            # entrypoint derived.my_job:main
```

## YAML contract

See `schemas/derived_job.schema.json`. Each job declares:

- `name` — listed in `definitions[].enabled_datasets` alongside dataset ids
- `entrypoint` — `derived.<module>:<callable>` (module file `python/derived/<module>.py`)
- `depends_on` — other dataset or derived job names in the same repo
- `tables[]` — output schema (columns, indexes, `foreign_keys` for multi-table bundles)

Jobs must **not** return in-memory row maps. Write one `{table}.csv` per output table under `ctx.output_dir` (see `DerivedJobContext`).

## Entrypoint API

```python
from pipeline.derived_context import DerivedJobContext

def main(ctx: DerivedJobContext) -> None:
    out = ctx.csv_path_for_table("my_table")
    # read upstream via psycopg + ctx.schema / ctx.database_url
    # write CSV with header row matching YAML columns
```

`ctx.output_uri` is a `file://` directory when `OPENDATA_LANDING_BACKEND=local` (default **`profile: lite`**). With `OPENDATA_LANDING_BACKEND=s3`, `output_uri` is an `s3://{bucket}/derived/{repo}/{job}/{run_id}/` prefix; jobs still write CSVs under `ctx.output_dir` locally and the framework uploads after the run.

## Execution

| Variable | Values | Purpose |
|----------|--------|---------|
| `OPENDATA_DERIVED_RUNNER` | `local` (default), `docker` | How to invoke job code |
| `OPENDATA_DERIVED_IMAGE` | image ref | Required when runner is `docker` |
| `OPENDATA_LANDING_BACKEND` | `local` (default), `s3` | Land derived CSVs on S3/MinIO |
| `OPENDATA_LOAD_BACKEND` | `copy_local` (default), `s3_copy_rds` | Local COPY or RDS server-side S3 import |
| `DATABASE_URL` | Postgres DSN | Read-only upstream queries + load |
| `S3_BUCKET`, `S3_*` | landing zone | Required when landing backend is `s3` |

Optional per-repo image: `repo.yml` → `derived_image` (used by docker runner).

Build the example worker image:

```bash
docker build -f examples/definition-repo/docker/Dockerfile.derived -t opendata-derived-example:local .
export OPENDATA_DERIVED_IMAGE=opendata-derived-example:local
export OPENDATA_DERIVED_RUNNER=docker
```

## Dagster

Derived jobs register as the same four-segment asset keys as datasets: `repo / schema / job_name / table_name`. Each YAML job is one `@multi_asset` bundle: materializing one or more table keys in a run executes the derived job **once** and reloads all output tables atomically (`can_subset=True`; selecting any sibling still runs the full bundle).

```bash
export DATABASE_URL=postgresql://opendata:opendata@localhost:5432/opendata
export OPENDATA_DAGSTER_MATERIALIZE=full
export OPENDATA_DAGSTER_DEFINITION_LOAD=embedded
dagster dev -m pipeline.dagster_defs
```

Upstream datasets must be loaded first (e.g. materialize `sample_csv` before `greeting_letter_counts`).

## Examples

| Job | Depends on | Outputs |
|-----|------------|---------|
| `greeting_letter_counts` | `sample_csv` | `letter_counts` |
| `building_rollups` | `bundle_demo` | `building_stats`, `large_buildings` (FK bundle) |

Validate:

```bash
python3 scripts/validate_definitions.py --repo examples/definition-repo
```

E2E (Postgres required):

```bash
export OPENDATA_DERIVED_E2E=1
export DATABASE_URL=postgresql://opendata:opendata@localhost:5432/opendata
python3 -m pytest tests/test_derived_e2e.py -q
```

## Trust model

Derived code is part of the definition repo (AGPL does not cover private repos). Pin git refs and review Python in CI before enabling jobs in production manifests.
