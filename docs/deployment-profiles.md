# Deployment profiles

Deployments declare a **`profile`** on `definitions.yml` (JSON Schema: `lite` | `standard` | `scaled`). The profile selects how extract, derived jobs, and load run.

**JustFix parallel POC** uses **`standard`** only. OSS adopters should use **`lite`** unless they operate their own AWS stack.

## Comparison

| Profile | Host model | Extract | Derived jobs | Load |
|---------|------------|---------|--------------|------|
| `lite` | Single Docker Compose host | In-process on orchestrator | `OPENDATA_DERIVED_RUNNER=local` or `docker` on same host | COPY from local CSV (`copy_local`) |
| `standard` | **Split EC2** orchestrator + API + **RDS PostgreSQL** + **S3** (no EKS) | In-process + S3 landing; daytime **extract** assets | `OPENDATA_DERIVED_RUNNER=docker` on orchestrator | Server-side COPY (`s3_copy_rds`); overnight **load** assets |
| `scaled` | Aurora + S3 + EKS + split services (**archived** for JustFix) | EKS Jobs (archived) | EKS Jobs (archived) | `s3_copy_rds` |

When `profile` is omitted, the framework treats the deployment as **`lite`**.

## Standard profile (JustFix POC)

**Infrastructure:** [`infra/aws/`](https://github.com/JustFixNYC/opendata-etl/blob/main/infra/aws/README.md) — RDS PostgreSQL 16 (`db.t4g.medium` POC default), S3 landing, EC2 orchestrator + EC2 API, ECR, SSM secrets.

**Manifest:** [`examples/definitions.poc.yml`](https://github.com/JustFixNYC/opendata-etl/blob/main/examples/definitions.poc.yml) — `profile: standard` with a subset of `enabled_datasets` for validation.

**Environment defaults** (orchestrator; also written to SSM `{prefix}/runtime/standard_env` after `terraform apply`):

| Variable | Value |
|----------|--------|
| `OPENDATA_LANDING_BACKEND` | `s3` |
| `OPENDATA_LOAD_BACKEND` | `s3_copy_rds` |
| `OPENDATA_DERIVED_RUNNER` | `docker` |
| `OPENDATA_EXTRACT_EXECUTOR` | `local` |
| `OPENDATA_DAGSTER_MATERIALIZE` | `full` (when running real materializations) |
| `S3_BUCKET` | Terraform output `landing_bucket_name` |
| `DATABASE_URL` | Built from SSM master password + `database_endpoint` |
| `OPENDATA_PG_OWNER_ROLE` | `opendata_admin` on RDS POC (Terraform master user) |

**Dagster:** Split **extract** / **load** asset keys (`{repo}/{schema}/{dataset}/{extract|load}/{table}`); schedules use **America/New_York** for extract (daytime) vs load (22:00–07:00 window). Dagster metadata DB on POC: **SQLite** on orchestrator (`DAGSTER_HOME`).

**Guides:**

- [First-time deploy (standard / POC)](deployment/aws-first-deploy.md)
- [RDS S3 COPY bootstrap](deployment/aws-s3-copy-bootstrap.md)
- [Database access via SSM](deployment/aws-database-access.md)
- [Components explained](deployment/aws-components.md) — read RDS/S3/EC2 sections; Aurora/EKS sections are historical

## Lite quick start

1. Copy `examples/definitions.local.yml` (includes `profile: lite`).
2. Start the stack:

   ```bash
   docker compose up --build -d
   ```

3. Set materialization:

   ```bash
   export OPENDATA_DAGSTER_MATERIALIZE=full
   export OPENDATA_DERIVED_RUNNER=local
   ```

4. Open Dagster at `http://localhost:3000`, materialize datasets then derived jobs.

Derived CSVs land under `data/definitions_work/derived_runs/{repo}/{job}/{run_id}/` on the orchestrator host (`OPENDATA_LANDING_BACKEND=local`, the default).

With `OPENDATA_LANDING_BACKEND=s3`, objects use `s3://{S3_BUCKET}/derived/{repo}/{job}/{run_id}/{table}.csv`; extract staging uses `s3://{S3_BUCKET}/extract/{dataset}/{date}/{table}.csv`.

## Scaled profile (archived for JustFix)

`profile: scaled` in [`examples/definitions.prod.yml`](https://github.com/JustFixNYC/opendata-etl/blob/main/examples/definitions.prod.yml) illustrated Aurora + EKS. Active Terraform for JustFix is **19b (RDS, no EKS)**. OSS teams may still use archived modules under `infra/aws/_archived/`.

- [AWS scaled overview](deployment/aws-scaled.md) — historical EKS path
- [DigitalOcean mapping](deployment/digitalocean-scaled.md) — documentation only

## `enabled_datasets`

One list per definition repo entry — include **both** dataset ids and derived job `name` values. There is no separate `enabled_derived_jobs` key.

```yaml
definitions:
  - name: example_collection
    enabled_datasets:
      - sample_csv
      - greeting_letter_counts
```
