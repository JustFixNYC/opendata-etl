# Deployment profiles

Deployments declare a **`profile`** on `definitions.yml` (JSON Schema: `lite` | `standard` | `scaled`). The profile selects how extract, derived jobs, and load run. OSS adopters should use **`lite`** only.

## Comparison

| Profile | Host model | Extract | Derived jobs | Load |
|---------|------------|---------|--------------|------|
| `lite` | Single Docker Compose host | In-process on orchestrator | `OPENDATA_DERIVED_RUNNER=local` or `docker` on same host | COPY from local CSV |
| `standard` | Stepping stone | Multiprocess + S3 landing | Docker or small EKS | Download S3 → COPY (`copy_local`) |
| `scaled` | Aurora + S3 + EKS + split services (Step 19+) | EKS Jobs (Step 22) | EKS Jobs (Step 21) | Server-side COPY (Step 20) |

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
- Server-side `COPY` from S3 into Aurora (Step 20)

**AWS guide:** [AWS scaled deployment](deployment/aws-scaled.md) — apply Terraform, EC2 Dagster orchestrator (reference), EKS workers, smoke tests.

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
