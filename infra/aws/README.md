# AWS scaled infrastructure (Terraform)

Reference IaC for **`profile: scaled`** deployments: Aurora PostgreSQL, S3 landing bucket, EKS cluster for batch Jobs, ECR repositories, split security groups (API / orchestrator / workers), IAM roles, and SSM parameters for secrets.

**Orchestrator reference path:** EC2 instance with SSM access running Dagster (documented in [`docs/deployment/aws-scaled.md`](../../docs/deployment/aws-scaled.md)). **Alternative:** Dagster on EKS — same Terraform outputs; different install steps in the guide.

## Layout

```text
infra/aws/
├── main.tf                 # Root module wiring
├── variables.tf / outputs.tf
├── terraform.tfvars.example
└── modules/
    ├── network/            # VPC, public/private subnets, NAT
    ├── security_groups/    # aurora, orchestrator, api, eks_workers
    ├── aurora/             # Aurora PostgreSQL cluster + SSM password
    ├── landing/            # S3 bucket (extract/, derived/) + lifecycle
    ├── eks/                # EKS cluster, node group, IRSA worker role
    ├── ecr/                # framework + derived image repos
    ├── iam/                # EC2 instance profiles + SSM placeholders
    ├── orchestrator/       # Reference EC2 Dagster host
    └── api_host/           # Optional split API EC2
```

## Prerequisites

- Terraform >= 1.5
- AWS CLI configured (`aws sts get-caller-identity`)
- IAM permissions to create VPC, RDS, S3, EKS, EC2, IAM, SSM

## Quick start

```bash
cd infra/aws
cp terraform.tfvars.example terraform.tfvars
# Edit admin_cidr_blocks, region, sizing

terraform init
terraform validate
terraform plan -out=tfplan
# terraform apply tfplan   # requires credentials; creates billable resources
```

## Post-apply

1. Read `terraform output` (cluster name, bucket, SSM paths, smoke commands).
2. Enable **PostGIS** on Aurora (one-time): connect as master user, `CREATE EXTENSION postgis;` per schema after framework provisioning.
3. Push framework image to `ecr_framework_repository_url`; definition-repo derived images to `derived` repo (tag per repo).
4. On the orchestrator EC2 (SSM Session Manager), set `DATABASE_URL`, `S3_BUCKET`, and flags from SSM `/runtime/scaled_env`.
5. Steps **20–22** add server-side COPY and EKS Job submitters in application code.

## Secrets

Passwords and connection strings are stored in **SSM Parameter Store** (SecureString where applicable). **Do not** commit `terraform.tfvars` with secrets or check generated passwords into git.

## Cost note

Default variables provision NAT gateway, Aurora `db.r6g.large`, and a multi-node EKS group. Use smaller classes and `single_nat_gateway = true` for dev accounts; destroy with `terraform destroy` when finished experimenting.
