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

| Service      | Purpose |
|--------------|---------|
| `postgres`   | PostgreSQL 16 + PostGIS (`postgis/postgis:16-3.4`). |
| `minio`      | S3-compatible landing zone. Console on host port `MINIO_CONSOLE_PORT` (default 9001). |
| `minio-init` | One-shot init: creates `S3_BUCKET` (default `opendata-landing`) via `mc mb --ignore-existing`. |
| `provision`  | One-shot init: `scripts/provision_roles.py` for schemas, read roles, and `opendata_auth` from `OPENDATA_DEFINITIONS_MANIFEST_PATH`. |
| `dagster`    | `dagster dev` with skeleton dataset assets from `pipeline.factory` (`pipeline.dagster_defs`). |
| `api`        | FastAPI read-only API: YAML-driven routes from loaded definition repos (Step 10); query execution is stubbed until Step 11. |

`dagster` and `api` start only after `minio-init` and `provision` exit successfully.

**Blockers / placeholders (Step 4+):**

- Dagster assets include **skeleton dataset tables** (Steps 6–8) plus **dbt models** when a definition repo contains `models/dbt_project.yml` and `dbt parse` succeeds at definition load time (Step 9). Install `dbt` on the host or use the project Docker image (`.[compose]` includes `dbt-core` + `dbt-postgres` + `dagster-dbt`).
- The API registers routes from ``api_endpoints/*.yml`` (Step 10); SQL is not executed until Step 11 (per-role pools + validation).
- **S3 landing (Step 18):** set `OPENDATA_LANDING_BACKEND=s3` and `OPENDATA_LOAD_BACKEND=copy_local` to land extract/derived CSVs on MinIO and download before COPY. The landing bucket (`S3_BUCKET`, default `opendata-landing`) is created automatically by `minio-init` on `docker compose up`; `dagster` and `api` start only after that init succeeds. On AWS RDS use `OPENDATA_LOAD_BACKEND=s3_copy_rds` (see [aws-s3-copy-bootstrap.md](deployment/aws-s3-copy-bootstrap.md)). Paths: `extract/{dataset}/{date}/{table}.csv` and `derived/{repo}/{job}/{run_id}/{table}.csv`. Default `local` keeps CSVs on disk only.

## Environment variables

Copy `.env.example` to `.env` and adjust. Compose injects paths used by later steps when wiring entrypoints:

- `OPENDATA_DEFINITIONS_MANIFEST_PATH` — path to `definitions.yml` **inside the container** (image includes `examples/`).
- `OPENDATA_DEFINITIONS_WORK_DIR` — writable clone target passed as `work_dir` to `load_definitions`.
- **Host-only `dagster dev`:** if `.env` still has Compose defaults like `/workspace/examples/definitions.local.yml` and that path does not exist on your machine, `pipeline.factory` **falls back** to `examples/definitions.local.yml` and `data/definitions_work` under the repo root (with a `UserWarning`). Prefer unsetting those two vars or setting them to real host paths when running outside Docker.
- `OPENDATA_DAGSTER_DEFINITION_LOAD` — `auto` (default in code when unset), `clone`, or `embedded`. With `examples/definitions.local.yml`, the placeholder HTTPS URL fails git clone, so **`auto` falls back** to the checked-in `examples/definition-repo` and you still see Dagster assets and **API routes** locally. The API uses the same resolver (`resolve_definitions_load_result`). Use `file://` remotes plus real refs (or `embedded`) when you want deterministic behavior without a warning.
- **Dagster monitoring (Step 12) and split extract/load (Step 21):** Optional dataset YAML ``schedule`` becomes **two stopped-by-default** schedules per dataset — **extract** (daytime) and **load** (overnight on ``profile: standard``). Asset keys are five segments for datasets: ``{repo}/{schema}/{dataset}/extract/{table}`` and ``…/load/{table}``; derived jobs keep four segments. On ``standard`` / ``scaled``, extract runs at **10:00** and load at **02:00** ``America/New_York`` (outside / inside the **22:00–07:00** NYC window). ``lite`` keeps the YAML cron for extract (UTC) and uses **07:00 UTC** for load. ``freshness_sla_hours`` applies to **load** outputs; ``extract_landing_exists`` checks run before load. **Slack:** set ``OPENDATA_SLACK_TOKEN`` and ``OPENDATA_SLACK_CHANNEL`` to register a run-failure sensor (still **stopped** until enabled in the UI); leave unset for local Compose. See ``pipeline/notifications.py`` and ``.env.example``.

**Cross-schema reads (dbt and SQL):** `depends_on` in `definitions.yml` orders repos only. Database `SELECT` on another repo’s schema requires **`reads_from_schemas`** with `access: read` on the upstream `schema`; `scripts/provision_roles.py` applies those grants to each consumer repo’s `opendata_<schema>_read` role. Do not grant an unprotected/public repo read access to a protected schema; materialize deidentified aggregate tables into the public repo’s own schema instead. If dbt runs as the table owner (`DATABASE_URL` in dev), Postgres already allows reads; if you introduce a dedicated dbt login later, grant it the same way provision grants read roles (and document the role alongside `reads_from_schemas`).
- `DATABASE_URL` — for **host-side** Python/Dagster use `127.0.0.1` (see `.env.example`). Compose `provision` / `dagster` / `api` always connect to hostname `postgres` inside the network (they do not inherit host `DATABASE_URL` from `.env`).
- `S3_*` — consumed by loaders/API; defaults match local Compose service names (`minio` hostname in-container).

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

**Compose (default):** a full `docker compose up` runs the `provision` init service after Postgres is healthy. It executes `scripts/provision_roles.py` against `OPENDATA_DEFINITIONS_MANIFEST_PATH` (default `examples/definitions.local.yml` in the image). No separate provisioning step is required for `dagster` / `api` to start.

Optional: set `OPENDATA_COMPOSE_PROVISION_LOAD_REPOS=1` in `.env` to pass `--load-repos` (clone manifest repos and apply `sql/functions/*.sql`). Off by default so local examples do not require private git remotes.

**Host-only Postgres or custom manifests:** from the repo root, with Compose Postgres listening on the host (default port 5432):

```bash
docker compose up -d postgres
export DATABASE_URL=postgresql://opendata:opendata@127.0.0.1:5432/opendata
python3 scripts/provision_roles.py --manifest examples/definitions.prod.yml
```

The script is idempotent. It reads the same `definitions.yml` contract as `load_definitions` (via `pipeline.definitions.ordered_deployment_definition_entries` for ordering and `reads_from_schemas` rules), creates one schema per `definitions[].schema`, creates `opendata_<schema>_read` and `opendata_public_read`, applies `protected` / non-`protected` membership (`GRANT` / `REVOKE` of the per-schema read role to `opendata_public_read`), applies explicit `reads_from_schemas`, and creates the `opendata_auth` schema placeholder for Step 11.

- Print SQL without connecting: `python3 scripts/provision_roles.py --manifest examples/definitions.prod.yml --print-sql`
- Optional: `OPENDATA_PG_OWNER_ROLE` (default `opendata`) must match the role that will own loaded tables so `ALTER DEFAULT PRIVILEGES ... FOR ROLE` applies to future objects.

**Smoke check (protected schema):** after provisioning with `examples/definitions.prod.yml`, connect as superuser, create a table in `ex_reports`, then `SET ROLE opendata_public_read` and confirm `SELECT` on that table fails while `SELECT` on a table in `ex_housing` succeeds. Automated equivalent: `OPENDATA_PROVISION_TEST_DATABASE_URL="$DATABASE_URL" python3 -m pytest -q tests/test_provisioning.py::test_live_postgres_public_read_cannot_select_protected_schema`.

## Host Dagster + Docker Postgres (Workflow A)

Common setup: ``docker compose up -d`` for Postgres/MinIO only, then run ``dagster dev`` or ``dg launch --assets`` on the **host** (venv with ``.[compose]``; ``dg.toml`` at repo root).

The hostname ``postgres`` in ``DATABASE_URL`` resolves only **inside** the Compose network. If Dagster loads a ``.env`` meant for containers, you will see:

```text
psycopg.OperationalError: failed to resolve host 'postgres'
```

Use **localhost** (published ``POSTGRES_PORT``, default 5432) for host-side commands:

```bash
export DATABASE_URL=postgresql://opendata:opendata@127.0.0.1:5432/opendata
export OPENDATA_DEFINITIONS_MANIFEST_PATH=examples/definitions.local.yml
export OPENDATA_DAGSTER_DEFINITION_LOAD=clone
export OPENDATA_DAGSTER_MATERIALIZE=full

python3 scripts/provision_roles.py --manifest examples/definitions.local.yml

Definition repos with `repo.yml` `sql_extensions: true` ship `sql/functions/*.sql` (API-facing Postgres functions). Apply them with `--local-repo` (checked-out tree) or `--load-repos` (clone from manifest), or rely on materialize `provision=True` hooks:

```bash
python3 scripts/provision_roles.py --manifest examples/definitions.local.yml \
  --local-repo examples/definition-repo
```

EXECUTE is granted on functions referenced in `api_endpoints/` SQL to each repo’s `opendata_<schema>_read` role.

dg launch --assets 'key:"example_collection/ex_housing/sample_csv/extract/rows"'
```

Set the same ``OPENDATA_DEFINITIONS_MANIFEST_PATH``, ``OPENDATA_DEFINITIONS_WORK_DIR``, and ``OPENDATA_DAGSTER_DEFINITION_LOAD`` as for ``dagster dev`` so ``dg`` loads the same manifest-backed definitions (see ``.env.example``).

Tip: keep ``DATABASE_URL`` with ``127.0.0.1`` in ``.env`` when you usually materialize from the host; use ``postgres`` only when running inside the ``dagster`` service (``docker compose exec -w /workspace dagster dg …``).

**Superseded:** ``dagster asset materialize -m pipeline.dagster_defs --select …`` — use ``dg launch --assets`` with [asset selection syntax](https://docs.dagster.io/guides/build/assets/asset-selection-syntax) (``key:"repo/schema/dataset/extract/table"`` for split assets).

**Shapefile (`nycc`) requires GDAL:** ``ogr2ogr`` must be on ``PATH`` and runnable. The framework Docker image installs ``gdal-bin`` (``Dockerfile``) so in-container materialize works without a host GDAL install.

Smoke check after ``docker compose build dagster``:

```bash
docker compose run --rm dagster ogr2ogr --version
```

On the host (Workflow A), install GDAL separately (``brew install gdal`` / ``apt install gdal-bin``). If ``ogr2ogr`` crashes with ``SIGABRT`` or ``Library not loaded`` (Homebrew dylib mismatch), run ``brew reinstall gdal`` (sometimes ``brew reinstall abseil re2 gdal``).

## Non-Docker workflows

- Validate definitions load from repo root (requires ``.[compose]``): ``dg check toml`` and ``dg check defs --no-check-yaml`` (this repo builds Definitions in ``pipeline.factory``, not ``pipeline/defs`` autoload). Equivalent: ``dagster definitions validate -m pipeline.dagster_defs``.
- Dagster (after installing optional `compose` deps from `pyproject.toml`): `dagster dev -m pipeline.dagster_defs` from the repo root.
- API: `uvicorn api.app:app --reload --host 0.0.0.0 --port 8000`.

## Health checks

Compose defines `healthcheck` for Postgres (`pg_isready`), MinIO (`/minio/health/live`), Dagster (HTTP GET `/` with a long `start_period`), and the API (`GET /healthz`). If the Dagster probe proves flaky for your environment, treat it as best-effort until the webserver behavior stabilizes on your version.
