# AWS standard / POC infrastructure (Terraform)

Reference IaC for **`profile: standard`** deployments: **RDS PostgreSQL 16**, S3 landing bucket, EC2 orchestrator (optional API EC2), ECR repositories, split security groups, IAM roles, RDS S3-import IAM, and SSM parameters for secrets.

**No EKS** in active Terraform (Step 19b). The Step 19 EKS and Aurora modules are archived under [`_archived/`](_archived/).

## Layout

```text
infra/aws/
├── main.tf                 # Root module wiring
├── variables.tf / outputs.tf
├── terraform.tfvars.example
├── _archived/
│   ├── eks/                # Archived EKS module (Step 19)
│   └── aurora/             # Archived Aurora module (Step 19)
└── modules/
    ├── network/            # VPC, public/private subnets, NAT
    ├── security_groups/    # postgres, orchestrator, api
    ├── postgres_rds/       # RDS PostgreSQL + S3 import IAM + role association
    ├── landing/            # S3 bucket (extract/, derived/) + lifecycle
    ├── ecr/                # framework + derived image repos
    ├── iam/                # EC2 instance profiles + SSM placeholders
    ├── orchestrator/       # Reference EC2 Dagster host
    └── api_host/           # Optional split API EC2
```

## Prerequisites

- Terraform >= 1.5
- AWS CLI v2 + **Session Manager plugin**
- `aws sts get-caller-identity` works
- IAM permissions to create VPC, RDS, S3, EC2, IAM, SSM

## Quick start

For a real environment, apply this module from an operator deployment repo pinned to a framework release tag. Direct use from this directory is useful for framework development and POC experiments.

```bash
cd infra/aws
cp terraform.tfvars.example terraform.tfvars
# Edit admin_cidr_blocks, region, sizing

terraform init
terraform validate
terraform plan -out=tfplan
# terraform apply tfplan   # human: requires credentials; creates billable resources
```

## Post-apply

1. Read `terraform output -json` — record `landing_bucket_name`, `database_endpoint`, `master_password_ssm`, `orchestrator_instance_id`.
2. Bootstrap RDS extensions: [`docs/deployment/aws-s3-copy-bootstrap.md`](../../docs/deployment/aws-s3-copy-bootstrap.md).
3. Database access (Postico / psql): [`docs/deployment/aws-database-access.md`](../../docs/deployment/aws-database-access.md).
4. Application: `OPENDATA_LOAD_BACKEND=s3_copy_rds`; keep POC/prod manifests in the deployment repo and set `create_api_instance = true` for the split API EC2 path.
5. Deploy guide: [`docs/deployment/aws-first-deploy.md`](../../docs/deployment/aws-first-deploy.md).
6. Orchestrator S3 bootstrap: [`examples/deployment-repo/README-automation.md`](../../examples/deployment-repo/README-automation.md) — upload runtime bundle + manifest, then `docker compose` via `user_data`.
7. Validation runbook: [`docs/deployment/aws-poc-validation.md`](../../docs/deployment/aws-poc-validation.md).

## Secrets

Passwords and connection strings are stored in **SSM Parameter Store** (SecureString where applicable). **Do not** commit `terraform.tfvars` with secrets or check generated passwords into git.

## Cost note

POC defaults: single NAT gateway, `db.t4g.medium`, one orchestrator EC2. Destroy with `terraform destroy` when finished experimenting.
