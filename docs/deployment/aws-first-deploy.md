# First-time AWS deploy (standard profile / POC)

End-to-end guide for the **parallel POC** stack: **RDS PostgreSQL 16**, S3 landing, **EC2 orchestrator** (Dagster + batch), and **EC2 API** (FastAPI). No EKS. Assumes macOS or Linux and basic terminal comfort.

For **what each AWS piece does**, read [Components explained](aws-components.md) (sections on VPC, RDS, S3, and split EC2 still apply; ignore Aurora/EKS where marked archived).

## Before you start

### Checklist

- [ ] AWS account with **billing alerts** (Cost Explorer → Budgets).
- [ ] IAM user or role with permission to create VPC, RDS, S3, EC2, IAM, SSM (AdministratorAccess for first apply is simplest; narrow later).
- [ ] **Terraform** >= 1.5 and **AWS CLI** v2 + **Session Manager plugin** (`aws sts get-caller-identity`).
- [ ] **Docker** (build/push images to ECR).
- [ ] POC manifest: [`examples/definitions.poc.yml`](https://github.com/JustFixNYC/opendata-etl/blob/main/examples/definitions.poc.yml) (`profile: standard`, subset `enabled_datasets`).

### Host layout (standard profile)

| Host | Role |
|------|------|
| **Orchestrator EC2** | Dagster webserver + daemon; daytime **extract**; overnight **load**, derived (docker), dbt |
| **API EC2** | FastAPI read-only API only |
| **RDS PostgreSQL** | Writer for batch and API (no reader replica in POC) |
| **S3** | Landing `extract/` and `derived/` prefixes |

### Estimated time

- First `terraform apply`: ~20–30 minutes (no EKS).
- Bootstrap + provisioning + Docker: 1–2 hours.
- First split materialization: dataset-dependent; Part 9 below is a short checklist — master plan **Step 23** adds the full phased runbook.

## Part 1 — Terraform state (POC: local)

For a **throwaway POC**, the default **local** `terraform.tfstate` under `infra/aws/` is fine. Destroy with `terraform destroy` when finished.

For **shared production**, add an S3 remote backend later (post-MVP). Do not commit state files with secrets.

## Part 2 — Configure variables

```bash
cd infra/aws
cp terraform.tfvars.example terraform.tfvars
```

Edit `terraform.tfvars`:

| Variable | What to set |
|----------|-------------|
| `environment` | `poc` for parallel stack |
| `admin_cidr_blocks` | Office/VPN CIDR for Dagster UI (port 3000) — **not** `0.0.0.0/0` unless intentional |
| `api_ingress_cidr_blocks` | CIDR allowed to reach API port 8000 on the API security group |
| `postgres_instance_class` | POC default `db.t4g.medium` |
| `single_nat_gateway` | `true` for cost |
| `landing_bucket_force_destroy` | `true` for ephemeral POC only |
| `create_orchestrator_instance` | `true` |
| `create_api_instance` | `true` for full standard POC (split API EC2) |

Review cost in your org’s planning docs before `apply`.

## Part 3 — Terraform init, plan, apply

```bash
terraform init
terraform validate   # human: requires terraform CLI
terraform plan -out=tfplan
# Read the plan: one aws_db_instance, zero EKS resources
terraform apply tfplan
```

Save outputs (fill master plan 19b table):

```bash
terraform output -json | jq .
terraform output -raw landing_bucket_name
terraform output -raw database_endpoint
terraform output -raw master_password_ssm
terraform output -raw orchestrator_instance_id
terraform output -raw api_instance_id
```

Important outputs: `landing_bucket_name`, `database_endpoint`, `master_password_ssm`, `orchestrator_instance_id`, `api_instance_id`, `ecr_framework_repository_url`, `standard_runtime_env_ssm`, `smoke_check_commands`.

### Smoke tests (infrastructure)

```bash
aws s3 ls "s3://$(terraform output -raw landing_bucket_name)/"

aws ssm get-parameter \
  --name "$(terraform output -raw master_password_ssm)" \
  --with-decryption --query Parameter.Value --output text

# Reference env flags (standard profile):
aws ssm get-parameter \
  --name "$(terraform output -raw standard_runtime_env_ssm)" \
  --query Parameter.Value --output text
```

Expect `OPENDATA_LOAD_BACKEND=s3_copy_rds` in that SSM reference string.

Database access from your laptop: [Database access (SSM)](aws-database-access.md). PostGIS + `aws_s3` bootstrap: [RDS S3 COPY bootstrap](aws-s3-copy-bootstrap.md).

## Part 4 — PostGIS, aws_s3, and provisioning

1. Run bootstrap SQL from [aws-s3-copy-bootstrap.md](aws-s3-copy-bootstrap.md) (PostGIS, `aws_commons`, `aws_s3`, optional import smoke).
2. Port-forward RDS (or connect from orchestrator) and set `DATABASE_URL` with master user `opendata_admin`.
3. Provision schemas and roles:

```bash
export PGPASSWORD="$(aws ssm get-parameter \
  --name "$(terraform output -raw master_password_ssm)" \
  --with-decryption --query Parameter.Value --output text)"
export DATABASE_URL="postgresql://opendata_admin:${PGPASSWORD}@127.0.0.1:15432/opendata?sslmode=require"

python scripts/provision_roles.py \
  --manifest examples/definitions.poc.yml \
  --table-owner-role opendata_admin
```

Use `OPENDATA_PG_OWNER_ROLE=opendata_admin` on the orchestrator for loads.

## Part 5 — Push Docker images to ECR

```bash
REGION=us-east-1
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
ECR_URL=$(terraform output -raw ecr_framework_repository_url)

aws ecr get-login-password --region "$REGION" | \
  docker login --username AWS --password-stdin "$ACCOUNT.dkr.ecr.$REGION.amazonaws.com"

cd /path/to/opendata-etl
docker build -t opendata-etl:poc .
docker tag opendata-etl:poc "$ECR_URL:poc"
docker push "$ECR_URL:poc"
```

Build and push **derived** images per definition repo when you enable `derived_python` jobs (`ecr_derived_repository_url`).

## Part 6 — Orchestrator EC2 (Dagster)

```bash
ORCH_ID=$(terraform output -raw orchestrator_instance_id)
aws ssm start-session --target "$ORCH_ID"
```

On the instance (Amazon Linux 2023):

```bash
sudo dnf install -y docker git
sudo systemctl enable --now docker
sudo usermod -aG docker ssm-user
# newgrp docker or re-login for group
```

Pull the framework image (same ECR login as Part 5).

Create `/etc/opendata-etl/env` (root-only, `chmod 600`):

```bash
# Standard profile defaults (match SSM .../runtime/standard_env)
OPENDATA_LANDING_BACKEND=s3
OPENDATA_LOAD_BACKEND=s3_copy_rds
OPENDATA_DERIVED_RUNNER=docker
OPENDATA_EXTRACT_EXECUTOR=local
OPENDATA_DAGSTER_MATERIALIZE=full
OPENDATA_PG_OWNER_ROLE=opendata_admin
OPENDATA_S3_COPY_REGION=us-east-1

S3_BUCKET=<landing_bucket_name from terraform output>
DATABASE_URL=postgresql://opendata_admin:<password>@<database_endpoint>:5432/opendata?sslmode=require

OPENDATA_DEFINITIONS_MANIFEST_PATH=/etc/opendata-etl/definitions.yml
OPENDATA_DEFINITIONS_WORK_DIR=/var/lib/opendata-etl/definitions_work

# Dagster metadata DB for POC (SQLite on orchestrator disk)
DAGSTER_HOME=/var/lib/opendata-etl/dagster_home

# Optional Slack (Step 12)
# OPENDATA_SLACK_TOKEN=...
# OPENDATA_SLACK_CHANNEL=...
```

Copy [`examples/definitions.poc.yml`](https://github.com/JustFixNYC/opendata-etl/blob/main/examples/definitions.poc.yml) to `/etc/opendata-etl/definitions.yml`.

Run Dagster (example):

```bash
sudo mkdir -p /var/lib/opendata-etl/dagster_home
sudo docker run -d --name dagster \
  --restart unless-stopped \
  --env-file /etc/opendata-etl/env \
  -p 3000:3000 \
  -v /var/lib/opendata-etl:/var/lib/opendata-etl \
  -v /etc/opendata-etl/definitions.yml:/etc/opendata-etl/definitions.yml:ro \
  -v /var/run/docker.sock:/var/run/docker.sock \
  "$ECR_URL:poc" \
  dagster dev -h 0.0.0.0 -p 3000 -m pipeline.dagster_defs
```

Mounting `docker.sock` allows `OPENDATA_DERIVED_RUNNER=docker` on the same host. Harden for production (dedicated derived runner, pinned images).

Dagster UI via **SSM port forwarding** (private instance):

```bash
aws ssm start-session --target "$ORCH_ID" \
  --document-name AWS-StartPortForwardingSession \
  --parameters "portNumber=3000,localPortNumber=3000"
```

Open `http://localhost:3000`. Enable schedules in the UI when ready (registered **STOPPED** by default).

## Part 7 — API EC2 (split deploy)

When `create_api_instance = true`, Terraform creates a **second** private EC2 with the API instance profile (SSM + ECR pull; **no** S3 landing writes).

```bash
API_ID=$(terraform output -raw api_instance_id)
aws ssm start-session --target "$API_ID"
```

On the API instance:

```bash
sudo dnf install -y docker
sudo systemctl enable --now docker
# ECR login + pull same framework image tag as orchestrator
```

Create `/etc/opendata-etl/api.env` (API-only):

```bash
DATABASE_URL=postgresql://opendata_admin:<password>@<database_endpoint>:5432/opendata?sslmode=require
OPENDATA_API_ROLE_DSNS={"opendata_public_read":"postgresql://..."}
# OPENDATA_API_KEYS_LOOKUP_DSN=  # same as DATABASE_URL if keys live on writer
```

Build role DSNs after `provision_roles.py` (per-schema read roles). Issue keys with `scripts/issue_api_key.py` from a host that can reach RDS.

Run FastAPI:

```bash
sudo docker run -d --name api \
  --restart unless-stopped \
  --env-file /etc/opendata-etl/api.env \
  -p 8000:8000 \
  "$ECR_URL:poc" \
  uvicorn api.app:create_app --factory --host 0.0.0.0 --port 8000
```

Expose port **8000** to users via **SSM port forward**, VPN, or an org-specific **ALB/TLS** terminator in front of the API security group (`api_ingress_cidr_blocks`). The API instance does not run Dagster or batch jobs.

Smoke test (from a forwarded session or allowed CIDR):

```bash
curl -sS http://127.0.0.1:8000/healthz
```

## Part 8 — Runtime reference (SSM)

Terraform writes a **non-secret** reference parameter at `{ssm_prefix}/runtime/standard_env` (output `standard_runtime_env_ssm`). It documents:

- `OPENDATA_LANDING_BACKEND=s3`
- `OPENDATA_LOAD_BACKEND=s3_copy_rds`
- `OPENDATA_DERIVED_RUNNER=docker` (derived jobs via docker on orchestrator)
- `OPENDATA_EXTRACT_EXECUTOR=local`
- `S3_BUCKET=<landing bucket id>`

Copy these into orchestrator and API env files; add `DATABASE_URL` and secrets separately from SSM SecureString parameters.

## Part 9 — First split materialization

Dataset assets use **5-segment keys** with `extract` and `load` phases (Step 21). On `profile: standard`, factory schedules place **extract** outside **22:00–07:00 America/New_York** and **load** inside that window.

1. In Dagster, confirm assets from `definitions.poc.yml` (subset: `fixture_hello`, `rentstab_v2`, `nycc`).
2. Materialize **`fixture_hello`** **extract** assets first; verify `s3://<bucket>/extract/...` objects.
3. Materialize matching **load** assets; confirm tables in `nyc_housing` and server-side COPY (no multi-GB download on EC2 disk for load).
4. Repeat for `rentstab_v2` or `nycc` when validating Tier B sources.
5. Hit a configured API endpoint on the API host after data exists.

Full phased runbook (Terraform through derived + dbt): master plan **Step 23** (next doc pass).

## Troubleshooting

| Symptom | Likely cause |
|---------|----------------|
| `terraform plan` shows EKS resources | Wrong branch/tfvars; active tree is 19b (RDS only) |
| Cannot reach RDS from laptop | DB is private — use SSM port forward ([aws-database-access.md](aws-database-access.md)) |
| Dagster empty asset list | Bad manifest path; clone/auth failure for `nycdb2` git URL |
| Load fails on S3 | Missing `aws_s3` bootstrap or RDS S3 import IAM ([aws-s3-copy-bootstrap.md](aws-s3-copy-bootstrap.md)) |
| `s3_copy_rds` errors | `OPENDATA_LOAD_BACKEND` not set; URI not `s3://` |
| API 503 / pool errors | `OPENDATA_API_ROLE_DSNS` not set or provisioning not run |
| Derived job fails | Docker socket not mounted on orchestrator; image not in ECR |

## What's next

- [Ongoing maintenance](aws-maintenance.md) (adjust for RDS where Aurora is mentioned)
- Master plan **Step 23**: parallel POC validation runbook (phases A–C)
- [Deployment profiles](../deployment-profiles.md) — `standard` vs `lite` vs archived `scaled`

## Related

- [`infra/aws/README.md`](https://github.com/JustFixNYC/opendata-etl/blob/main/infra/aws/README.md)
- [RDS S3 COPY bootstrap](aws-s3-copy-bootstrap.md)
- [Database access (SSM)](aws-database-access.md)
- Archived EKS/Aurora path: [AWS scaled overview](aws-scaled.md)
