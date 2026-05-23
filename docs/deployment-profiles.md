# Deployment profiles

Deployments declare a **`profile`** on `definitions.yml` (JSON Schema: `lite` | `standard` | `scaled`). The profile selects how extract, derived jobs, and load run. OSS adopters should use **`lite`** only.

## Comparison

| Profile | Host model | Extract | Derived jobs | Load |
|---------|------------|---------|--------------|------|
| `lite` | Single Docker Compose host | In-process on orchestrator | `OPENDATA_DERIVED_RUNNER=local` or `docker` on same host | COPY from local CSV |
| `standard` | EC2 orchestrator + RDS + S3 (no EKS) | In-process + S3 landing | `OPENDATA_DERIVED_RUNNER=docker` | Server-side COPY (`s3_copy_rds`) |
| `scaled` | Aurora + S3 + EKS + split services (archived for JustFix) | EKS Jobs (archived) | EKS Jobs (archived) | Server-side COPY (`s3_copy_rds`) |

When `profile` is omitted, the framework treats the deployment as **`lite`**.

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

## Scaled overview (Steps 18–22)

Production manifests use `profile: scaled` (see `examples/definitions.prod.yml`). That path adds:

- S3 landing for extract and derived `output_uri` (`OPENDATA_LANDING_BACKEND=s3`)
- Aurora PostgreSQL and Terraform under [`infra/aws/`](../infra/aws/README.md)
- EKS Job workers instead of local/docker runners (Steps 21–22)
- Server-side `COPY` from S3 into RDS/Aurora via `OPENDATA_LOAD_BACKEND=s3_copy_rds` (Step 20; bootstrap in [aws-s3-copy-bootstrap.md](deployment/aws-s3-copy-bootstrap.md))

**AWS guides (OSS):**

- [Overview](deployment/aws-scaled.md)
- [Components explained](deployment/aws-components.md) — VPC, Aurora, S3, EKS, IAM in plain language
- [First-time deploy](deployment/aws-first-deploy.md) — Terraform through first materialization
- [Ongoing maintenance](deployment/aws-maintenance.md) — upgrades, scaling, change windows

Organization-specific cost and runbooks stay in your internal planning repo (not in this framework).

**DigitalOcean:** [DO service mapping](deployment/digitalocean-scaled.md) (documentation only; no Terraform in-repo).

Env flags: `OPENDATA_LANDING_BACKEND`, `OPENDATA_LOAD_BACKEND`, `OPENDATA_DERIVED_EXECUTOR`, `OPENDATA_EXTRACT_EXECUTOR` (see SSM reference in Terraform `modules/iam`).

## `enabled_datasets`

One list per definition repo entry — include **both** dataset ids and derived job `name` values. There is no separate `enabled_derived_jobs` key.

```yaml
definitions:
  - name: example_collection
    enabled_datasets:
      - sample_csv
      - greeting_letter_counts
```
