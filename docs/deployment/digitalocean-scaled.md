# DigitalOcean scaled deployment (mapping)

Full Terraform for DigitalOcean is **not** maintained in this repository (see master plan post-MVP). Use this page to map AWS reference components to DO services when running **`profile: scaled`** with the same application env vars.

| AWS (Terraform `infra/aws/`) | DigitalOcean equivalent |
|------------------------------|-------------------------|
| Aurora PostgreSQL | **Managed Databases** (PostgreSQL 16, enable PostGIS via extension) |
| S3 landing bucket | **Spaces** (S3-compatible API — set `S3_ENDPOINT_URL`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `S3_BUCKET`) |
| EKS | **DOKS** (Kubernetes Jobs for extract/derived workers) |
| ECR | **DO Container Registry** |
| EC2 orchestrator | **Droplet** (Docker + Dagster) or Dagster on DOKS |
| SSM Parameter Store | **Doppler**, **1Password**, or Droplet env files / DO Secrets |
| IAM / IRSA | DOKS **workload identity** or pod secrets for Spaces access |
| Split security groups | **Cloud Firewalls** (API vs orchestrator vs worker node pools) |

## Env vars (unchanged)

The framework reads the same variables on any cloud:

- `OPENDATA_LANDING_BACKEND=s3` with Spaces endpoint
- `OPENDATA_LOAD_BACKEND=copy_local` (until server-side COPY is configured for managed Postgres)
- `OPENDATA_DERIVED_EXECUTOR=eks` / `OPENDATA_EXTRACT_EXECUTOR=eks` with DOKS
- `DATABASE_URL` pointing at managed Postgres

## Next steps

1. Provision managed Postgres + Spaces + DOKS manually or with your own Terraform/Pulumi.
2. Follow [`aws-scaled.md`](aws-scaled.md) for orchestrator vs worker split and image workflow, substituting DO services in the table above.
3. Contribute `infra/digitalocean/` via community PR if you want a maintained module set.
