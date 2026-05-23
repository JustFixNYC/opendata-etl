# AWS scaled deployment

Production deployments use **`profile: scaled`** in `definitions.yml` (see [`examples/definitions.prod.yml`](https://github.com/JustFixNYC/opendata-etl/blob/main/examples/definitions.prod.yml)). Terraform under [`infra/aws/`](https://github.com/JustFixNYC/opendata-etl/blob/main/infra/aws/README.md) provisions Aurora, S3 landing, EKS, ECR, and split security groups.

## Documentation map

| Guide | Who it is for |
|-------|----------------|
| [**Components explained**](aws-components.md) | Anyone new to AWS — what VPC, Aurora, S3, EKS, etc. do for opendata-etl |
| [**First-time deploy**](aws-first-deploy.md) | Operator doing the initial Terraform apply and Dagster install |
| [**Ongoing maintenance**](aws-maintenance.md) | Upgrades, scaling, Terraform change windows, backups |
| [**infra/aws/README.md**](https://github.com/JustFixNYC/opendata-etl/blob/main/infra/aws/README.md) | Module layout and quick Terraform commands |

Organization-specific sizing, budget, and runbooks belong in **your internal planning repo**, not in this OSS framework.

## Architecture (summary)

```mermaid
flowchart TB
  orch[EC2 Dagster orchestrator]
  api[API host]
  eks[EKS Job workers]
  s3[(S3 landing)]
  aurora[(Aurora PostgreSQL)]

  orch -->|submit Jobs Steps 21-22| eks
  eks -->|extract/ derived/ CSVs| s3
  orch -->|s3_copy_rds on RDS| s3
  orch -->|load + provision| aurora
  api -->|read-only SQL| aurora
```

| Role | Host | Responsibilities |
|------|------|------------------|
| **Orchestrator** | EC2 (reference) or EKS | Dagster schedules, load assets, EKS Job submission |
| **API** | Separate EC2 / ALB | FastAPI read-only queries only |
| **Workers** | EKS Jobs | Heavy extract downloads and derived Python (Steps 21–22) |
| **Landing** | S3 | `extract/…` and `derived/{repo}/{job}/{run_id}/…` |
| **Database** | Aurora PostgreSQL | One schema per definition repo; PostGIS per schema |

## Quick Terraform apply

```bash
cd infra/aws
cp terraform.tfvars.example terraform.tfvars
# Edit admin_cidr_blocks and sizing — see aws-first-deploy.md

terraform init
terraform validate
terraform plan -out=tfplan
terraform apply tfplan
```

Record outputs: `landing_bucket_name`, `aurora_cluster_endpoint`, `eks_cluster_name`, `ecr_framework_repository_url`, `eks_worker_irsa_role_arn`, `ssm_parameter_prefix`.

For full steps (remote state, ECR, Dagster on EC2, first materialization), follow [**First-time deploy**](aws-first-deploy.md).

## Runtime env (scaled)

```bash
export OPENDATA_LANDING_BACKEND=s3
export OPENDATA_LOAD_BACKEND=s3_copy_rds         # or copy_local for non-RDS Postgres
export OPENDATA_DERIVED_EXECUTOR=eks             # Step 21
export OPENDATA_EXTRACT_EXECUTOR=eks             # Step 22
export S3_BUCKET="<landing-bucket>"
export DATABASE_URL="postgresql://..."
```

## PostGIS, ECR, IRSA, smoke tests

See [**First-time deploy**](aws-first-deploy.md) (Parts 4–9) and [**Maintenance**](aws-maintenance.md).

## Related

- [Deployment profiles](../deployment-profiles.md)
- [Local development](../local-development.md) (`profile: lite`)
- [DigitalOcean scaled](digitalocean-scaled.md) (mapping stub)
