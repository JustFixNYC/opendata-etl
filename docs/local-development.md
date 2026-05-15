# Local development with Docker Compose

This page complements `README.md` and the master plan Step 4. It focuses on **pinned git refs**, **`file://` definition repos**, and how they connect to `pipeline.definitions.load_definitions`.

## Prerequisites

- Docker with Compose v2 (`docker compose`).
- Git on the host (used by the definitions loader when you run Python outside Compose).

## Bring up the stack

From the framework repo root:

```bash
docker compose config   # validates compose (no image pull)
docker compose up --build -d
```

Services:

| Service    | Purpose |
|------------|---------|
| `postgres` | PostgreSQL 16 + PostGIS (`postgis/postgis:16-3.4`). |
| `minio`    | S3-compatible landing zone. Console on host port `MINIO_CONSOLE_PORT` (default 9001). |
| `dagster`  | `dagster dev` with skeleton dataset assets from `pipeline.factory` (`pipeline.dagster_defs`). |
| `api`      | FastAPI read-only API: YAML-driven routes from loaded definition repos (Step 10); query execution is stubbed until Step 11. |

**Blockers / placeholders (Step 4+):**

- Dagster assets include **skeleton dataset tables** (Steps 6–8) plus **dbt models** when a definition repo contains `models/dbt_project.yml` and `dbt parse` succeeds at definition load time (Step 9). Install `dbt` on the host or use the project Docker image (`.[compose]` includes `dbt-core` + `dbt-postgres` + `dagster-dbt`).
- The API registers routes from ``api_endpoints/*.yml`` (Step 10); SQL is not executed until Step 11 (per-role pools + validation).
- Create the MinIO bucket named in `S3_BUCKET` (default `opendata-landing`) before extractors write objects; Compose does not auto-create it.

## Environment variables

Copy `.env.example` to `.env` and adjust. Compose injects paths used by later steps when wiring entrypoints:

- `OPENDATA_DEFINITIONS_MANIFEST_PATH` — path to `definitions.yml` **inside the container** (image includes `examples/`).
- `OPENDATA_DEFINITIONS_WORK_DIR` — writable clone target passed as `work_dir` to `load_definitions`.
- **Host-only `dagster dev`:** if `.env` still has Compose defaults like `/workspace/examples/definitions.local.yml` and that path does not exist on your machine, `pipeline.factory` **falls back** to `examples/definitions.local.yml` and `data/definitions_work` under the repo root (with a `UserWarning`). Prefer unsetting those two vars or setting them to real host paths when running outside Docker.
- `OPENDATA_DAGSTER_DEFINITION_LOAD` — `auto` (default in code when unset), `clone`, or `embedded`. With `examples/definitions.local.yml`, the placeholder HTTPS URL fails git clone, so **`auto` falls back** to the checked-in `examples/definition-repo` and you still see Dagster assets and **API routes** locally. The API uses the same resolver (`resolve_definitions_load_result`). Use `file://` remotes plus real refs (or `embedded`) when you want deterministic behavior without a warning.
- **dbt (Step 9):** set `DBT_PROFILES_DIR` to the directory containing `profiles.yml` (default in Compose: `examples/definition-repo/models/dbt_profile` inside the image). Set `DBT_TARGET_SCHEMA` to the deployment row’s `definitions[].schema` when it differs from the profile default (`ex_housing` for the example). Run `dbt parse` / `dbt run` from `examples/definition-repo/models` or use Dagster’s dbt assets (same vars). The example model `sample_rows_summary` reads `sample_csv.rows`; load that table with the framework loader before `dbt run`.

**Cross-schema reads (dbt and SQL):** `depends_on` in `definitions.yml` orders repos only. Database `SELECT` on another repo’s schema requires **`cross_repo_grants`** with `access: read` on the foreign `schema`; `scripts/provision_roles.py` applies those grants to each repo’s `opendata_<schema>_read` role. If dbt runs as the table owner (`DATABASE_URL` in dev), Postgres already allows reads; if you introduce a dedicated dbt login later, grant it the same way provision grants read roles (and document the role alongside `cross_repo_grants`).
- `DATABASE_URL`, `S3_*` — consumed by future loaders/API; defaults match local Compose service names.

## Pinned refs and `definitions.yml`

Production-like behavior uses a deployment manifest (`definitions.yml`) where each definition repo has a **pinned `ref`** (commit SHA, tag, or branch name) alongside `url`:

```yaml
definitions:
  - name: example_collection
    url: https://github.com/example-org/example-definition-repo.git
    ref: abc1234deadbeef   # prefer immutable SHAs or release tags
    schema: ex_housing
    protected: false
```

The loader clones `url` and checks out `ref` into `work_dir / name` after validating the manifest. See **`pipeline.definitions.load_definitions`**, which takes:

- `manifest_path` — filesystem path to the deployment YAML (same idea as `OPENDATA_DEFINITIONS_MANIFEST_PATH`).
- `work_dir` — parent directory for per-repo checkouts (same idea as `OPENDATA_DEFINITIONS_WORK_DIR`).

```python
from pathlib import Path
from pipeline.definitions import load_definitions

result = load_definitions(
    Path("examples/definitions.local.yml"),
    Path("data/definitions_work"),
)
for repo in result.repos:
    print(repo.name, repo.path, repo.ref)
```

## `file://` URLs for offline iteration

The loader accepts **`https://` and `file://`** git URLs only. For a local clone of a definition repo (for example while authoring YAML), initialize or use a bare/regular git repo and point the manifest at a **`file://` URL** and a concrete **`ref`** (branch, tag, or commit):

```yaml
definitions:
  - name: example_collection
    url: "file:///absolute/path/to/your-definition-repo.git"
    ref: main
    schema: ex_housing
    protected: false
```

Notes:

- The path must be visible **where the loader runs** (on the host when running Python locally, or inside the container when wired into entrypoints). For in-container loads, mount the repo or bake it into a dev image.
- `file://` must point at a **git** remote (bare `.git` directory or `.git` suffix as used in tests), not a plain working tree path, unless that path is a valid git URL for `git clone`.
- Prefer pinned SHAs or tags for anything you intend to reproduce; branches are convenient but mutable.

## Postgres schema and roles (Step 5)

From the repo root, with Compose Postgres listening on the host (default port 5432):

```bash
docker compose up -d postgres
export DATABASE_URL=postgresql://opendata:opendata@127.0.0.1:5432/opendata
python3 scripts/provision_roles.py --manifest examples/definitions.prod.yml
```

The script is idempotent. It reads the same `definitions.yml` contract as `load_definitions` (via `pipeline.definitions.ordered_deployment_definition_entries` for ordering and `cross_repo_grants` rules), creates one schema per `definitions[].schema`, creates `opendata_<schema>_read` and `opendata_public_read`, applies `protected` / non-`protected` membership (`GRANT` / `REVOKE` of the per-schema read role to `opendata_public_read`), applies explicit `cross_repo_grants`, and creates the `opendata_auth` schema placeholder for Step 11.

- Print SQL without connecting: `python3 scripts/provision_roles.py --manifest examples/definitions.prod.yml --print-sql`
- Optional: `OPENDATA_PG_OWNER_ROLE` (default `opendata`) must match the role that will own loaded tables so `ALTER DEFAULT PRIVILEGES ... FOR ROLE` applies to future objects.

**Smoke check (protected schema):** after provisioning with `examples/definitions.prod.yml`, connect as superuser, create a table in `nyc_reports`, then `SET ROLE opendata_public_read` and confirm `SELECT` on that table fails while `SELECT` on a table in `nyc_housing` succeeds. Automated equivalent: `OPENDATA_PROVISION_TEST_DATABASE_URL="$DATABASE_URL" python3 -m pytest -q tests/test_provisioning.py::test_live_postgres_public_read_cannot_select_protected_schema`.

## Non-Docker workflows

- Validate manifests: `python3 scripts/validate_definitions.py --examples-default`.
- Dagster (after installing optional `compose` deps from `pyproject.toml`): `dagster dev -m pipeline.dagster_defs` from the repo root.
- API: `uvicorn api.app:app --reload --host 0.0.0.0 --port 8000`.

## Health checks

Compose defines `healthcheck` for Postgres (`pg_isready`), MinIO (`/minio/health/live`), Dagster (HTTP GET `/` with a long `start_period`), and the API (`GET /healthz`). If the Dagster probe proves flaky for your environment, treat it as best-effort until the webserver behavior stabilizes on your version.
