# First-time AWS deploy (scaled profile)

End-to-end guide: **AWS account prep → Terraform → application install → first run**. Assumes macOS or Linux and basic comfort with a terminal. No Windows-specific steps.

For **what each AWS piece does**, read [Components explained](aws-components.md) first.

## Before you start

### Checklist

- [ ] AWS account with **billing alerts** configured (Cost Explorer → Budgets).
- [ ] IAM user or role with permission to create VPC, RDS, S3, EKS, EC2, IAM, SSM (AdministratorAccess for first apply is simplest; narrow later).
- [ ] **Terraform** >= 1.5 and **AWS CLI** v2 installed and configured (`aws sts get-caller-identity`).
- [ ] **kubectl** (for EKS smoke tests).
- [ ] **Docker** (to build/push images).
- [ ] `definitions.yml` for production (start from [`examples/definitions.prod.yml`](../../examples/definitions.prod.yml)).

### Choose orchestrator host

| Option | Complexity | Recommendation |
|--------|------------|----------------|
| **EC2 + Dagster** | Lower | **Default** — matches `infra/aws/` Terraform |
| Dagster on EKS | Higher | Teams already running Kubernetes for other apps |

This guide follows **EC2**.

### Estimated time

- First Terraform apply: 30–45 minutes (EKS is slow).
- Application setup: 1–2 hours.
- First successful materialization: depends on dataset size.

## Part 1 — Terraform remote state (recommended)

Storing state in S3 avoids losing track of what AWS resources exist.

```bash
# One-time: create state bucket (replace UNIQUE suffix)
aws s3 mb s3://opendata-etl-tfstate-UNIQUE --region us-east-1
aws s3api put-bucket-versioning \
  --bucket opendata-etl-tfstate-UNIQUE \
  --versioning-configuration Status=Enabled
```

Create `infra/aws/backend.tf` (local file, not committed if it contains account-specific names):

```hcl
terraform {
  backend "s3" {
    bucket = "opendata-etl-tfstate-UNIQUE"
    key    = "opendata-etl/prod/terraform.tfstate"
    region = "us-east-1"
  }
}
```

Skip this section only for a **throwaway** experiment; you will regret it for production.

## Part 2 — Configure variables

```bash
cd infra/aws
cp terraform.tfvars.example terraform.tfvars
```

Edit `terraform.tfvars`:

| Variable | What to set |
|----------|-------------|
| `admin_cidr_blocks` | Your office/VPN public IP range — **not** `0.0.0.0/0` for Dagster |
| `api_ingress_cidr_blocks` | `0.0.0.0/0` only if API is truly public; tighten if behind VPN |
| `aurora_instance_class` | Size for your data (see maintenance doc) |
| `eks_node_desired_size` | Start with `1`–`2`; scale up for parallel overnight jobs |
| `create_orchestrator_instance` | `true` |
| `create_api_instance` | `true` if you want Terraform to create a split API EC2 |

Review cost implications in your organization’s planning docs before `apply`.

## Part 3 — Terraform init, plan, apply

```bash
terraform init
terraform validate
terraform plan -out=tfplan
# Read the plan carefully: count of resources and instance types
terraform apply tfplan
```

Save outputs:

```bash
terraform output > ~/opendata-etl-outputs.txt
terraform output -json | jq .
```

Important outputs: `landing_bucket_name`, `aurora_cluster_endpoint`, `eks_cluster_name`, `ecr_framework_repository_url`, `ssm_parameter_prefix`, `orchestrator_instance_id`.

### Smoke tests (infrastructure)

```bash
aws eks update-kubeconfig --name "$(terraform output -raw eks_cluster_name)" --region us-east-1
kubectl get nodes

aws s3 ls "s3://$(terraform output -raw landing_bucket_name)/"

# Aurora password (do not paste into tickets)
aws ssm get-parameter \
  --name "$(terraform output -raw aurora_master_password_ssm)" \
  --with-decryption --query Parameter.Value --output text
```

Connect to Aurora from a host that can reach the VPC (orchestrator via SSM):

```bash
psql "postgresql://opendata_admin:<password>@<aurora_endpoint>:5432/opendata?sslmode=require" \
  -c "SELECT version();"
```

## Part 4 — PostGIS and provisioning

On first connect as master user:

```sql
CREATE EXTENSION IF NOT EXISTS postgis;
```

Run framework **provisioning** (schemas and roles) from the orchestrator once `DATABASE_URL` is set — see framework docs for `run_provisioning` / deployment scripts your org uses.

## Part 5 — Push Docker images to ECR

```bash
REGION=us-east-1
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
ECR_URL=$(terraform output -raw ecr_framework_repository_url)

aws ecr get-login-password --region $REGION | \
  docker login --username AWS --password-stdin "$ACCOUNT.dkr.ecr.$REGION.amazonaws.com"

cd /path/to/opendata-etl
docker build -t opendata-etl:prod .
docker tag opendata-etl:prod "$ECR_URL:prod"
docker push "$ECR_URL:prod"
```

Repeat for **derived** images per definition repo (`infra/aws` ECR `derived` repository).

## Part 6 — Install Dagster on the orchestrator (EC2)

```bash
INSTANCE_ID=$(terraform output -raw orchestrator_instance_id)
aws ssm start-session --target "$INSTANCE_ID"
```

On the instance (Amazon Linux 2023):

```bash
sudo dnf install -y docker git
sudo systemctl enable --now docker
sudo usermod -aG docker ssm-user

# Pull framework image
ACCOUNT=<account-id>
REGION=us-east-1
ECR_URL=<from terraform output>
aws ecr get-login-password --region $REGION | \
  sudo docker login --username AWS --password-stdin "$ACCOUNT.dkr.ecr.$REGION.amazonaws.com"
sudo docker pull "$ECR_URL:prod"
```

Create env file `/etc/opendata-etl/env` (root-only permissions):

```bash
OPENDATA_LANDING_BACKEND=s3
OPENDATA_LOAD_BACKEND=copy_local
OPENDATA_DERIVED_EXECUTOR=local
OPENDATA_EXTRACT_EXECUTOR=in_process
S3_BUCKET=<landing_bucket_name>
DATABASE_URL=postgresql://opendata_admin:<password>@<aurora_host>:5432/opendata?sslmode=require
OPENDATA_DEFINITIONS_MANIFEST_PATH=/etc/opendata-etl/definitions.yml
OPENDATA_DEFINITIONS_WORK_DIR=/var/lib/opendata-etl/definitions_work
# Slack (optional)
# OPENDATA_SLACK_TOKEN=...
# OPENDATA_SLACK_CHANNEL=...
```

Copy `definitions.yml` to `/etc/opendata-etl/definitions.yml`. Until EKS executors (Steps 21–22) are implemented, use `in_process` / `local` runners; switch to `eks` when ready.

Run Dagster (example — adjust volumes to mount env and work dir):

```bash
sudo docker run -d --name dagster \
  --restart unless-stopped \
  --env-file /etc/opendata-etl/env \
  -p 3000:3000 \
  -v /var/lib/opendata-etl:/var/lib/opendata-etl \
  -v /etc/opendata-etl/definitions.yml:/etc/opendata-etl/definitions.yml:ro \
  "$ECR_URL:prod" \
  dagster dev -h 0.0.0.0 -p 3000 -m pipeline.dagster_defs
```

Open Dagster UI via **SSM port forwarding** (because the instance is private):

```bash
aws ssm start-session --target "$INSTANCE_ID" \
  --document-name AWS-StartPortForwardingSession \
  --parameters "portNumber=3000,localPortNumber=3000"
```

Visit `http://localhost:3000`.

## Part 7 — API host (optional split)

If `create_api_instance = true`, repeat a similar Docker setup on the API instance with **only** API env vars (`DATABASE_URL`, `OPENDATA_API_ROLE_DSNS`, keys lookup DSN). Expose port 8000 behind your TLS terminator (ALB, Caddy, etc.) — adding an ALB is org-specific.

For high public traffic, plan an **Application Load Balancer** and health checks; a single small EC2 may not be enough.

## Part 8 — First materialization

1. In Dagster, confirm assets loaded from `definitions.yml`.
2. Materialize one **small** dataset first (`OPENDATA_DAGSTER_MATERIALIZE=full`).
3. Verify row counts in Aurora and objects under `s3://<bucket>/extract/…`.
4. Materialize one **derived** job; check `derived/…` prefix in S3.
5. Hit a simple API endpoint if configured.

## Part 9 — Billing and Slack

- Confirm **AWS Budget** alert to your team email/Slack.
- Enable opendata-etl **Slack run-failure sensor** (framework Step 12) in Dagster UI.

## Troubleshooting

| Symptom | Likely cause |
|---------|----------------|
| `terraform apply` fails on EKS | Insufficient IAM; quota limits in account |
| Cannot reach Aurora from laptop | DB is private — use SSM on orchestrator |
| Dagster empty asset list | Bad `definitions.yml` path or clone/auth failure |
| S3 AccessDenied | Instance profile or IRSA role missing bucket policy |
| EKS nodes NotReady | Node group still launching; check `kubectl describe node` |

## What’s next

- [Ongoing maintenance](aws-maintenance.md)
- Framework Steps 20–22: server-side COPY, EKS extract/derived executors
- Organization-specific sizing and cost: maintain in your internal planning repo, not here

## Related

- [AWS scaled overview](aws-scaled.md)
- [Components explained](aws-components.md)
- [`infra/aws/README.md`](../../infra/aws/README.md)
