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
- First split materialization: dataset-dependent; Part 9 below is a short checklist — full phased runbook: [**Parallel POC validation**](aws-poc-validation.md) (Step 23).

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

Read-role **passwords** for the API are set later in Part **7.2** (provisioning only creates roles).

## Part 5 — Push Docker images to ECR

Run from the **framework repo root**. Terraform state is under `infra/aws/` — `terraform output` only works there (or with `-chdir`).

```bash
cd /path/to/opendata-etl

REGION=us-east-1
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)

cd infra/aws
ECR_URL=$(terraform output -raw ecr_framework_repository_url)
if [ -z "$ECR_URL" ]; then
  echo "ERROR: ecr_framework_repository_url is empty."
  echo "  Run Part 3 (terraform apply) from infra/aws, or cd infra/aws before terraform output."
  exit 1
fi
cd ../..

aws ecr get-login-password --region "$REGION" | \
  docker login --username AWS --password-stdin "$ACCOUNT.dkr.ecr.$REGION.amazonaws.com"

docker build -t opendata-etl:poc .
docker tag opendata-etl:poc "${ECR_URL}:poc"
docker push "${ECR_URL}:poc"
```

Alternative from repo root without `cd`:  
`ECR_URL=$(terraform -chdir=infra/aws output -raw ecr_framework_repository_url)`

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

**Pull the framework image from ECR** (required before `docker run`). Run these commands **on the orchestrator EC2** (inside `aws ssm start-session`), not on your laptop. Part 5 push is from the laptop only.

The ECR Docker username is always the literal string **`AWS`** (not your IAM user name). The password is the token from `aws ecr get-login-password`.

```bash
REGION=us-east-1
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
# Orchestrator IAM can pull images but cannot call ecr:DescribeRepositories — set URL explicitly.
# On laptop: terraform -chdir=infra/aws output -raw ecr_framework_repository_url
ECR_URL="${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com/opendata-etl-poc/framework"

aws ecr get-login-password --region "$REGION" | \
  sudo docker login --username AWS --password-stdin "${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com"

sudo docker pull "${ECR_URL}:poc"
```

On the orchestrator, `aws` uses the **instance profile** (no access keys). If you run the same login on your **Mac** for testing, omit `sudo` (Docker Desktop does not use sudo).

Use **`sudo docker login`** when you use **`sudo docker run`** — credentials are per user; `ssm-user` login does not apply to root.

**Common mistakes:** `--username terraform` or your email → always **`AWS`**; `sudo` on a Mac → password prompts and failed login; broken `ECR_URL` across two lines → invalid pull URL.

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
AWS_DEFAULT_REGION=us-east-1

S3_BUCKET=<landing_bucket_name from terraform output>
DATABASE_URL=postgresql://opendata_admin:<password>@<database_endpoint>:5432/opendata?sslmode=require

OPENDATA_DEFINITIONS_MANIFEST_PATH=/etc/opendata-etl/definitions.yml
OPENDATA_DEFINITIONS_WORK_DIR=/var/lib/opendata-etl/definitions_work
OPENDATA_DAGSTER_DEFINITION_LOAD=clone

# Dagster metadata DB for POC (SQLite on orchestrator disk)
DAGSTER_HOME=/var/lib/opendata-etl/dagster_home

# Optional Slack (Step 12)
# OPENDATA_SLACK_TOKEN=...
# OPENDATA_SLACK_CHANNEL=...
```

Install the POC manifest on the orchestrator (same file as Part 4 provisioning):

```bash
sudo mkdir -p /etc/opendata-etl /var/lib/opendata-etl/definitions_work
sudo curl -fsSL -o /etc/opendata-etl/definitions.yml \
  https://raw.githubusercontent.com/JustFixNYC/opendata-etl/main/examples/definitions.poc.yml
```

Run Dagster (example):

```bash
REGION=us-east-1
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
ECR_URL="${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com/opendata-etl-poc/framework"
sudo mkdir -p /var/lib/opendata-etl/dagster_home /var/lib/opendata-etl/definitions_work
sudo docker pull "${ECR_URL}:poc"
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

**S3 credentials inside the Dagster container:** extract/load use the orchestrator **instance profile** via the default boto3 chain (no `S3_ACCESS_KEY_ID` in env). The EC2 **IMDS hop limit must be 2** so Docker can reach instance metadata. If extract fails with `Unable to locate credentials`, on your laptop:

```bash
ORCH_ID=$(terraform -chdir=infra/aws output -raw orchestrator_instance_id)
aws ec2 modify-instance-metadata-options \
  --instance-id "$ORCH_ID" \
  --http-put-response-hop-limit 2 \
  --http-endpoint enabled \
  --http-tokens required
```

Then on the orchestrator: `sudo docker restart dagster` and retry materialization. New Terraform applies set hop limit 2 by default (`modules/orchestrator`).

Dagster UI via **SSM port forwarding** (private instance):

```bash
ORCH_ID=$(terraform output -raw orchestrator_instance_id)
aws ssm start-session --target "$ORCH_ID" \
  --document-name AWS-StartPortForwardingSession \
  --parameters "portNumber=3000,localPortNumber=3000"
```

Open `http://localhost:3000`. Enable schedules in the UI when ready (registered **STOPPED** by default).

### Materialize POC assets (orchestrator)

After Dagster is running, materialize data so RDS has tables (required for Part **7** `GET /housing/hello/by-id`, and for full POC validation in Part **9**).

**How assets are named (`profile: standard`, Step 21 split):**

Each dataset has two phases — **extract** (download → S3) and **load** (server-side `s3_copy_rds` → Postgres). Asset keys have **five segments**:

```text
{repo}/{schema}/{dataset}/{extract|load}/{table}
```

POC examples (`definitions.poc.yml`):

| Step | Asset key (example) |
|------|-------------------|
| Extract `fixture_hello` | `nycdb2/nyc_housing/fixture_hello/extract/greetings` |
| Load `fixture_hello` | `nycdb2/nyc_housing/fixture_hello/load/greetings` |
| dbt (optional) | `nycdb2/nyc_housing/dbt/fixture_greeting_count` |

**Rules:** always materialize **extract** before **load** for the same dataset; load assets depend on extract landing objects in S3.

**Wait for definitions to load:** first container start clones `nycdb2` from GitHub (check `sudo docker logs -f dagster` until the webserver is ready).

Optional sanity check on the **orchestrator**:

```bash
sudo docker exec dagster dagster definitions validate -m pipeline.dagster_defs
```

**CLI note:** The framework image includes `dagster` (and `dagster dev`) but **not** the separate [`dagster-dg-cli`](https://pypi.org/project/dagster-dg-cli/) package (`dg` command). You may see a `SupersessionWarning` when using `dagster asset materialize`; it still works for POC. Use:

```bash
sudo docker exec dagster dagster asset materialize -m pipeline.dagster_defs \
  --select 'nycdb2/nyc_housing/<dataset>/extract/<table>'
```

Migrating docs/scripts to `dg launch --assets …` is **deferred** (needs `dagster-dg-cli` in the image and workspace layout review).

#### Minimum materialization (API smoke + quick wiring proof)

On the **orchestrator** (container name `dagster` from the `docker run` above):

```bash
REGION=us-east-1
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
ECR_URL="${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com/opendata-etl-poc/framework"

# 1) Extract — lands CSV under s3://<landing_bucket>/extract/...
sudo docker exec dagster dagster asset materialize -m pipeline.dagster_defs \
  --select 'nycdb2/nyc_housing/fixture_hello/extract/greetings'

# 2) Load — COPY from S3 into schema nyc_housing (requires Part 4 bootstrap + env DATABASE_URL/S3_BUCKET)
sudo docker exec dagster dagster asset materialize -m pipeline.dagster_defs \
  --select 'nycdb2/nyc_housing/fixture_hello/load/greetings'
```

Verify S3 (orchestrator instance profile can list the landing bucket):

```bash
BUCKET="$(aws ssm get-parameter --name /opendata-etl/poc/landing/bucket --query Parameter.Value --output text)"
# Or paste from laptop: terraform -chdir=infra/aws output -raw landing_bucket_name
aws s3 ls "s3://${BUCKET}/extract/" --recursive | head
```

Verify Postgres (laptop port forward to RDS, or `psql` on orchestrator with private `database_endpoint`):

```sql
SELECT count(*) FROM nyc_housing.greetings;
```

#### Via Dagster UI (same operations)

1. Open `http://localhost:3000` (SSM port forward to orchestrator **3000**).
2. Go to **Assets** → search `fixture_hello`.
3. Select the **extract** asset group (`…/extract/greetings`) → **Materialize**.
4. When extract succeeds, select **load** (`…/load/greetings`) → **Materialize**.

Use the **Launchpad** if you need to rematerialize a single asset; logs show extract vs load phases.

#### Extended POC materialization (Part 9)

For full parallel POC validation (second dataset + dbt), continue with Part **9** or the phased checklist in [Parallel POC validation](aws-poc-validation.md#phase-c--split-materialization-proof):

```bash
# Tier B extract — rentstab_v2 (CSV; works with stock image)
sudo docker exec dagster dagster asset materialize -m pipeline.dagster_defs \
  --select 'nycdb2/nyc_housing/rentstab_v2/extract/rentstab_v2'

# nycc (shapefile) requires ogr2ogr/GDAL — not in the stock Dockerfile today; verify:
sudo docker exec dagster sh -c 'command -v ogr2ogr || echo MISSING_GDAL'
# If MISSING_GDAL, use rentstab_v2 for Tier B proof or rebuild the image with gdal-bin (see docs/local-development.md).
sudo docker exec dagster dagster asset materialize -m pipeline.dagster_defs \
  --select 'nycdb2/nyc_housing/nycc/extract/nycc'

sudo docker exec dagster dagster asset materialize -m pipeline.dagster_defs \
  --select 'nycdb2/nyc_housing/rentstab_v2/load/rentstab_v2'

# dbt view after fixture_hello load
sudo docker exec dagster dagster asset materialize -m pipeline.dagster_defs \
  --select 'nycdb2/nyc_housing/dbt/fixture_greeting_count'
```

On `profile: standard`, **schedules** register extract at **10:00** and load at **02:00** `America/New_York` (outside / inside **22:00–07:00**). For manual runs you can materialize back-to-back; for schedule soak tests, enable jobs in the UI after wiring is proven.

**Diagnostics when nycdb2 assets are missing from the UI**

On the **orchestrator** (SSM session):

```bash
sudo docker exec dagster env | grep -E 'OPENDATA_DEFINITIONS|OPENDATA_DAGSTER_DEFINITION_LOAD'
sudo docker exec dagster cat /etc/opendata-etl/definitions.yml | head -30
sudo ls -la /var/lib/opendata-etl/definitions_work/nycdb2/repo.yml
sudo docker logs dagster 2>&1 | grep -iE 'load_definitions|git clone|embedded|UserWarning' | tail -20
sudo docker exec dagster dagster asset list -m pipeline.dagster_defs 2>/dev/null | grep nycdb2 | head
```

In the UI, search **`fixture_hello`** or **`nyc_housing`** — asset keys are five segments (`nycdb2/.../extract/...`).

**Troubleshooting materialization**

| Symptom | Check |
|---------|--------|
| Empty asset list / no **nycdb2** | Wrong manifest: container defaulted to image `definitions.local.yml` (`file://` path fails on EC2 → **embedded** `example_collection` fallback). Fix env + mount below; restart container |
| Only `example_collection` / `ex_housing` assets | Same as above — clone failed; check `docker logs dagster` for `load_definitions failed` or `git clone failed` |
| Extract fails | Outbound HTTPS/NAT; source URL reachable from orchestrator |
| Load fails S3 COPY | Part **4** `aws_s3` bootstrap; `OPENDATA_LOAD_BACKEND=s3_copy_rds`; `S3_BUCKET` in env |
| Load before extract | Run extract asset first; `extract_landing_exists` check on load |
| Extract: `Unable to locate credentials` on S3 put | Docker cannot reach EC2 instance profile when IMDS hop limit is **1** — set hop limit **2** (below) and restart `dagster` container |

## Part 7 — API EC2 (split deploy)

When `create_api_instance = true`, Terraform creates a **second** private EC2 for FastAPI only. To **validate** the API (routes + DB pools + optional key auth), complete **all** substeps below — not only `healthz`.

**Prerequisites**

- Part **4** (`provision_roles.py` with `examples/definitions.poc.yml`) — creates `opendata_public_read` and `opendata_nyc_housing_read` (no passwords yet).
- Part **5** image pushed to ECR as `:poc`.
- For `GET /housing/hello/by-id` to return rows: Part **6** (or **9**) `fixture_hello` **load** completed on the orchestrator.

### 7.1 — SSM session, Docker, ECR pull

On your **laptop** (from `infra/aws`):

```bash
API_ID=$(terraform output -raw api_instance_id)
aws ssm start-session --target "$API_ID"
```

On the **API instance**:

```bash
sudo dnf install -y docker
sudo systemctl enable --now docker
sudo usermod -aG docker ssm-user
```

**ECR login + pull** (on this API host; username must be **`AWS`**):

```bash
REGION=us-east-1
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
ECR_URL="${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com/opendata-etl-poc/framework"

aws ecr get-login-password --region "$REGION" | \
  sudo docker login --username AWS --password-stdin "${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com"

sudo docker pull "${ECR_URL}:poc"
```

If `GetAuthorizationToken` is **AccessDenied** on role `…-api`, from your laptop run `cd infra/aws && terraform apply` (adds ECR pull to the API IAM role), wait ~1 minute, retry.

### 7.2 — Read-role passwords (one-time, laptop + RDS port forward)

`provision_roles.py` creates `LOGIN` roles but **does not set passwords**. Set them once as `opendata_admin` (same SSM port forward as Part 4 — [Database access](aws-database-access.md)).

On your laptop (second terminal, forward session open):

```bash
cd infra/aws
export PGPASSWORD="$(aws ssm get-parameter \
  --name "$(terraform output -raw master_password_ssm)" \
  --with-decryption --query Parameter.Value --output text)"

psql "host=127.0.0.1 port=15432 dbname=opendata user=opendata_admin sslmode=require"
```

In `psql` (choose strong passwords; avoid `"` and `\` in passwords for simpler JSON in the next step):

```sql
ALTER ROLE opendata_nyc_housing_read PASSWORD 'your-nyc-housing-read-password';
ALTER ROLE opendata_public_read PASSWORD 'your-public-read-password';
```

For POC `definitions.poc.yml` (`schema: nyc_housing`, `protected: false`), the API needs DSNs for **both** roles in `OPENDATA_API_ROLE_DSNS`.

### 7.3 — POC manifest on the API host

The API loads routes from `api_endpoints/*.yml` in cloned definition repos (same manifest as the orchestrator).

On the **API instance**:

```bash
sudo mkdir -p /etc/opendata-etl /var/lib/opendata-etl/definitions_work
sudo curl -fsSL -o /etc/opendata-etl/definitions.yml \
  https://raw.githubusercontent.com/JustFixNYC/opendata-etl/main/examples/definitions.poc.yml
sudo chmod 644 /etc/opendata-etl/definitions.yml
```

(Or copy `/etc/opendata-etl/definitions.yml` from the orchestrator if you already created it there.)

### 7.4 — Create `/etc/opendata-etl/api.env`

On the **API instance**, set `DB_HOST` from your laptop: `terraform -chdir=infra/aws output -raw database_endpoint`. Use the read passwords from **7.2**.

```bash
DB_HOST="opendata-etl-poc-postgres.<password>.us-east-1.rds.amazonaws.com"
DB_PASS="$(aws ssm get-parameter \
  --name /opendata-etl/poc/postgres/master_password \
  --with-decryption --query Parameter.Value --output text)"
READ_PUBLIC_PASS='your-public-read-password'
READ_NYC_PASS='your-nyc-housing-read-password'

sudo tee /etc/opendata-etl/api.env >/dev/null <<EOF
DATABASE_URL=postgresql://opendata_admin:${DB_PASS}@${DB_HOST}:5432/opendata?sslmode=require
OPENDATA_API_KEYS_LOOKUP_DSN=postgresql://opendata_admin:${DB_PASS}@${DB_HOST}:5432/opendata?sslmode=require
OPENDATA_DEFINITIONS_MANIFEST_PATH=/etc/opendata-etl/definitions.yml
OPENDATA_DEFINITIONS_WORK_DIR=/var/lib/opendata-etl/definitions_work
OPENDATA_DAGSTER_DEFINITION_LOAD=clone
OPENDATA_API_ROLE_DSNS={"opendata_public_read":"postgresql://opendata_public_read:${READ_PUBLIC_PASS}@${DB_HOST}:5432/opendata?sslmode=require","opendata_nyc_housing_read":"postgresql://opendata_nyc_housing_read:${READ_NYC_PASS}@${DB_HOST}:5432/opendata?sslmode=require"}
EOF
sudo chmod 600 /etc/opendata-etl/api.env
```

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` / `OPENDATA_API_KEYS_LOOKUP_DSN` | Admin connection to read `opendata_auth.api_keys` when verifying API keys |
| `OPENDATA_API_ROLE_DSNS` | One libpq URI per read role the API executes SQL as |
| `OPENDATA_DEFINITIONS_*` | Clone `nycdb2` and register YAML routes (needs outbound HTTPS via NAT) |

### 7.5 — Run FastAPI container

On the **API instance** (`ECR_URL` from **7.1**):

```bash
sudo docker rm -f api 2>/dev/null || true
sudo docker run -d --name api \
  --restart unless-stopped \
  --env-file /etc/opendata-etl/api.env \
  -p 8000:8000 \
  -v /etc/opendata-etl/definitions.yml:/etc/opendata-etl/definitions.yml:ro \
  -v /var/lib/opendata-etl/definitions_work:/var/lib/opendata-etl/definitions_work \
  "${ECR_URL}:poc" \
  uvicorn api.app:create_app --factory --host 0.0.0.0 --port 8000
```

Check logs (first start clones `nycdb2` — may take a minute):

```bash
sudo docker logs -f api
```

### 7.6 — Smoke tests

**Port forward** Dagster/API from your laptop (new terminal):

```bash
cd infra/aws
aws ssm start-session --target "$(terraform output -raw api_instance_id)" \
  --document-name AWS-StartPortForwardingSession \
  --parameters "portNumber=8000,localPortNumber=8000"
```

**Liveness** (no DB required):

```bash
curl -sS http://127.0.0.1:8000/healthz
```

**YAML route** (anonymous if `opendata_public_read` can read `nyc_housing`; requires `fixture_hello` loaded):

```bash
curl -sS "http://127.0.0.1:8000/housing/hello/by-id?id=1"
```

**API key** (from laptop with RDS port forward and framework venv):

```bash
cd /path/to/opendata-etl
export DATABASE_URL="postgresql://opendata_admin:${PGPASSWORD}@127.0.0.1:15432/opendata?sslmode=require"
API_KEY=$(python3 scripts/issue_api_key.py --label "poc api smoke" --roles opendata_nyc_housing_read)
curl -sS -H "Authorization: Bearer ${API_KEY}" "http://127.0.0.1:8000/housing/hello/by-id?id=1"
```

**Part 7 validated when:** `healthz` returns `{"status":"ok"}`; `/housing/hello/by-id` returns JSON (or a clear 404/503 with actionable logs if data not loaded yet); authenticated curl works with a newly issued key.

The API instance does not run Dagster or batch jobs. Expose port **8000** via SSM forward, VPN, or ALB (`api_ingress_cidr_blocks`).

## Part 8 — Runtime reference (SSM)

Terraform writes a **non-secret** reference parameter at `{ssm_prefix}/runtime/standard_env` (output `standard_runtime_env_ssm`). It documents:

- `OPENDATA_LANDING_BACKEND=s3`
- `OPENDATA_LOAD_BACKEND=s3_copy_rds`
- `OPENDATA_DERIVED_RUNNER=docker` (derived jobs via docker on orchestrator)
- `OPENDATA_EXTRACT_EXECUTOR=local`
- `S3_BUCKET=<landing bucket id>`

Copy these into orchestrator and API env files; add `DATABASE_URL` and secrets separately from SSM SecureString parameters.

## Part 9 — First split materialization

**Minimum wiring** (fixture + API smoke): Part **6** — [Materialize POC assets](#materialize-poc-assets-orchestrator) (`fixture_hello` extract → load).

**Full POC subset** (second dataset + dbt + overnight window): follow the extended commands in that same section, or the phased checklist in [**Parallel POC validation**](aws-poc-validation.md) Phase C.

Checklist:

1. Confirm assets in Dagster UI (`fixture_hello`, `rentstab_v2`, `nycc` from `definitions.poc.yml`).
2. Materialize **extract** then **load** per dataset (5-segment keys; extract before load).
3. Verify S3 `extract/` prefixes and `nyc_housing` tables in RDS.
4. Optional: `rentstab_v2` / `nycc`, then dbt `fixture_greeting_count`.
5. API smoke on Part **7.6** after `fixture_hello` load.

On `profile: standard`, schedules use extract **10:00** and load **02:00** `America/New_York` (outside / inside **22:00–07:00**). Enable in the UI after manual runs succeed.

## Troubleshooting

| Symptom | Likely cause |
|---------|----------------|
| `terraform plan` shows EKS resources | Wrong branch/tfvars; active tree is 19b (RDS only) |
| Cannot reach RDS from laptop | DB is private — use SSM port forward ([aws-database-access.md](aws-database-access.md)) |
| Dagster empty asset list / no nycdb2 | `OPENDATA_DEFINITIONS_MANIFEST_PATH` + volume mount; `OPENDATA_DAGSTER_DEFINITION_LOAD=clone`; see Part **6** diagnostics; restart after env fix |
| Load fails on S3 | Missing `aws_s3` bootstrap or RDS S3 import IAM ([aws-s3-copy-bootstrap.md](aws-s3-copy-bootstrap.md)) |
| `s3_copy_rds` errors | `OPENDATA_LOAD_BACKEND` not set; URI not `s3://` |
| API 503 / pool errors | Complete Part **7.2–7.4** (`OPENDATA_API_ROLE_DSNS` + read-role passwords); re-run `provision_roles.py` if roles missing |
| API starts but no routes / 404 | Part **7.3–7.5**: manifest mount + `OPENDATA_DEFINITIONS_*`; check `docker logs api` for git clone errors |
| `hello_by_id` empty or 404 | Load `fixture_hello` first (Part **6** materialize); table `nyc_housing.greetings` must exist |
| Derived job fails | Docker socket not mounted on orchestrator; image not in ECR |
| `invalid reference format` / `:poc` | `ECR_URL` empty — run `terraform output` from `infra/aws` after apply |
| `no basic auth credentials` on ECR pull/run | Run login/pull **on orchestrator**; `--username AWS` (not IAM user); `sudo docker login` if using `sudo docker run` |
| `sudo: a password is required` during Part 6 | You are on your **Mac**, not EC2 — use SSM session, or drop `sudo` for Docker Desktop |
| ECR login “Sorry, try again” (Password) | Wrong `--username` (must be `AWS`) or `sudo` on Mac; not your AWS/IAM password |
| `AccessDenied` on `DescribeRepositories` | Expected on orchestrator — set `ECR_URL` manually (see Part 6); login can still succeed |
| `invalid reference format` after login | `ECR_URL` empty — fix URL, then `sudo docker pull "${ECR_URL}:poc"` again |
| ECR `AccessDenied` on **api** role | Run `terraform apply` in `infra/aws` (API IAM needs `ecr:GetAuthorizationToken`); see Part 7 |

## What's next

- [Ongoing maintenance](aws-maintenance.md) (adjust for RDS where Aurora is mentioned)
- [**Parallel POC validation**](aws-poc-validation.md) — phases A–C (Step 23)
- [Deployment profiles](../deployment-profiles.md) — `standard` vs `lite` vs archived `scaled`

## Related

- [`infra/aws/README.md`](https://github.com/JustFixNYC/opendata-etl/blob/main/infra/aws/README.md)
- [RDS S3 COPY bootstrap](aws-s3-copy-bootstrap.md)
- [Database access (SSM)](aws-database-access.md)
- Archived EKS/Aurora path: [AWS scaled overview](aws-scaled.md)
