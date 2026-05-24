# Parallel POC validation runbook (Step 23)

Operator checklist to prove the **parallel POC** stack end-to-end: Terraform apply (19b) through **first split materialization** on **new** RDS + S3 + split EC2 — **not** legacy production Aurora or cron.

**Prerequisites (framework Steps 19b–22):**

- `s3_copy_rds` load backend, split extract/load assets (`profile: standard` schedules), [`examples/definitions.poc.yml`](https://github.com/JustFixNYC/opendata-etl/blob/main/examples/definitions.poc.yml).
- Human AWS credentials with permission to apply Terraform and use SSM.

**Companion docs:**

| Topic | Doc |
|-------|-----|
| Terraform variables, ECR, EC2 env templates | [First-time AWS deploy](aws-first-deploy.md) |
| PostGIS + `aws_s3` + provisioning | [RDS S3 COPY bootstrap](aws-s3-copy-bootstrap.md) |
| Postico / `psql` via SSM | [Database access (SSM)](aws-database-access.md) |
| 19b operator checklist | `_planning/extra-plans/opendata-etl-step-19b-aws-readiness-for-step-20.plan.md` |

## Record Terraform outputs (19b)

After `terraform apply`, save outputs in the master plan **19b output table** (do not paste master password into tickets or chat):

```bash
cd infra/aws
terraform output -raw landing_bucket_name
terraform output -raw database_endpoint
terraform output -raw master_password_ssm
terraform output -raw orchestrator_instance_id
terraform output -raw api_instance_id
```

Example POC values (replace with your account):

| Output | Example |
|--------|---------|
| `landing_bucket_name` | `opendata-etl-poc-landing-654224513509` |
| `database_endpoint` | `opendata-etl-poc-postgres.clswhoz2jjq7.us-east-1.rds.amazonaws.com` |
| `master_password_ssm` | `/opendata-etl/poc/postgres/master_password` |
| `orchestrator_instance_id` | `i-031272d6e4db19441` |
| `api_instance_id` | `i-007456f0d198e332b` |

Infrastructure smoke (from `terraform output smoke_check_commands`):

```bash
aws s3 ls "s3://$(terraform output -raw landing_bucket_name)/"
aws ssm get-parameter \
  --name "$(terraform output -raw master_password_ssm)" \
  --with-decryption --query Parameter.Value --output text
```

## Success criteria (all phases)

| Criterion | How to verify |
|-----------|----------------|
| **Parallel stack only** | RDS endpoint and S3 bucket from **this** `terraform apply`; no legacy Aurora hostname or prod cron |
| **S3 landing + server-side load** | Extract objects under `s3://<bucket>/extract/...`; load uses `OPENDATA_LOAD_BACKEND=s3_copy_rds` (no multi-GB CSV on orchestrator disk) |
| **Split schedules** | On `profile: standard`, factory registers extract **10:00** and load **02:00** `America/New_York` (outside / inside **22:00–07:00** NYC) |
| **Overnight window** | When using default schedules (or manual load during 22:00–07:00 NYC), **load** assets finish before **07:00 America/New_York** |
| **API on split host** | `GET /healthz` on API EC2; fixture route returns data after `fixture_hello` load |
| **No EKS** | `terraform plan` shows zero EKS resources |

**Non-goals for this runbook:** production cutover, full ~40-dataset timeline, CI `terraform apply`, re-enabling EKS.

---

## Phase A — Parallel infra (Terraform + DB bootstrap)

**Goal:** VPC, RDS PostgreSQL 16, S3 landing, orchestrator + API EC2, ECR; PostGIS + `aws_s3`; schemas/roles for POC manifest.

### A1. Configure and apply Terraform (local state)

```bash
cd infra/aws
cp terraform.tfvars.example terraform.tfvars
# Edit: admin_cidr_blocks, api_ingress_cidr_blocks, environment=poc
terraform init
terraform validate
terraform plan -out=tfplan
# Confirm: one aws_db_instance, S3 bucket, two EC2 instances, zero EKS
terraform apply tfplan
```

Record outputs (section above). **Blockers** (quota, IAM, CIDR): note in master plan 19b table and stop until resolved.

### A2. SSM port forward + bootstrap SQL

In one terminal, start port forward ([Database access](aws-database-access.md)):

```bash
cd infra/aws
INSTANCE_ID=$(terraform output -raw orchestrator_instance_id)
DB_HOST=$(terraform output -raw database_endpoint)

aws ssm start-session \
  --target "$INSTANCE_ID" \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters "{\"host\":[\"$DB_HOST\"],\"portNumber\":[\"5432\"],\"localPortNumber\":[\"15432\"]}"
```

In another terminal, run bootstrap per [RDS S3 COPY bootstrap](aws-s3-copy-bootstrap.md):

1. Extensions: `postgis`, `aws_commons`, `aws_s3`
2. Verify RDS `s3Import` IAM association (`aws rds describe-db-instances …`)
3. **S3 import smoke** — upload tiny CSV, `aws_s3.table_import_from_s3` into `public._s3_import_smoke`

### A3. Provision roles (POC manifest)

From framework repo root (venv with `pip install -e ".[dev]"`):

```bash
cd infra/aws
export PGPASSWORD="$(aws ssm get-parameter \
  --name "$(terraform output -raw master_password_ssm)" \
  --with-decryption --query Parameter.Value --output text)"
export DATABASE_URL="postgresql://opendata_admin:${PGPASSWORD}@127.0.0.1:15432/opendata?sslmode=require"
export OPENDATA_PG_OWNER_ROLE=opendata_admin

cd ../..
python scripts/provision_roles.py \
  --manifest examples/definitions.poc.yml \
  --table-owner-role opendata_admin
```

**Phase A done when:** bootstrap SQL succeeds, S3 import smoke returns rows, `nyc_housing` schema exists, read roles created.

---

## Phase B — Application deploy (orchestrator + API EC2)

**Goal:** Framework image on ECR; Dagster on orchestrator (SQLite metadata); FastAPI on API EC2; env matches SSM `standard_env`.

Follow [First-time AWS deploy](aws-first-deploy.md) **Parts 5–8** with these POC specifics:

| Setting | Value |
|---------|--------|
| Image tag | `poc` (or your chosen tag) |
| Manifest on instances | `/etc/opendata-etl/definitions.yml` ← copy of `examples/definitions.poc.yml` |
| `DAGSTER_HOME` | `/var/lib/opendata-etl/dagster_home` (SQLite) |
| Orchestrator | Mount `docker.sock` if using `OPENDATA_DERIVED_RUNNER=docker` later |
| `DATABASE_URL` | `opendata_admin` @ `database_endpoint` (private DNS from EC2) |

### B1. Push image to ECR

Same as [First-time deploy — Part 5](aws-first-deploy.md#part-5--push-docker-images-to-ecr). From framework repo root:

```bash
cd /path/to/opendata-etl

REGION=us-east-1
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)

cd infra/aws
ECR_URL=$(terraform output -raw ecr_framework_repository_url)
if [ -z "$ECR_URL" ]; then
  echo "ERROR: ecr_framework_repository_url is empty — apply Terraform in infra/aws first."
  exit 1
fi
cd ../..

aws ecr get-login-password --region "$REGION" | \
  docker login --username AWS --password-stdin "$ACCOUNT.dkr.ecr.$REGION.amazonaws.com"

docker build -t opendata-etl:poc .
docker tag opendata-etl:poc "${ECR_URL}:poc"
docker push "${ECR_URL}:poc"
```

### B2. Orchestrator — validate definitions

On orchestrator (SSM session), after env file and manifest are in place:

```bash
docker run --rm -w /workspace \
  --env-file /etc/opendata-etl/env \
  -v /etc/opendata-etl/definitions.yml:/etc/opendata-etl/definitions.yml:ro \
  -v /var/lib/opendata-etl:/var/lib/opendata-etl \
  "$ECR_URL:poc" \
  dg check defs --no-check-yaml
```

Expect assets for `fixture_hello`, `rentstab_v2`, `nycc` (extract + load each) and dbt model `fixture_greeting_count`.

Port-forward Dagster UI (`aws ssm start-session` … `portNumber=3000`). Schedules register **STOPPED** — leave stopped until Phase C manual runs, then enable for soak tests.

### B3. API EC2 — health + keys

```bash
curl -sS http://127.0.0.1:8000/healthz
```

Issue an API key from a host with RDS access ([`scripts/issue_api_key.py`](https://github.com/JustFixNYC/opendata-etl/blob/main/scripts/issue_api_key.py)) using role `opendata_nyc_housing_read` (created by provisioning).

**Phase B done when:** `dg check defs --no-check-yaml` passes; Dagster UI lists POC assets; API `/healthz` returns 200.

---

## Phase C — Split materialization proof

**Goal:** Daytime **extract** for one small + one larger dataset; **load** (+ dbt) in overnight window; API smoke. Uses **5-segment** asset keys: `{repo}/{schema}/{dataset}/{extract|load}/{table}`.

POC manifest datasets:

| Dataset | Tier | Notes |
|---------|------|--------|
| `fixture_hello` | Small | CSV from GitHub raw; use first |
| `rentstab_v2` | Larger (~24 MB) | S3 public JustFix object |
| `nycc` | Larger (~860 KB zip) | Shapefile — **GDAL/`ogr2ogr` required** in container |

Default **standard** schedules (factory): extract **10:00**, load **02:00** `America/New_York`. For a **manual validation run**, materialize extract during local daytime and load during **22:00–07:00 America/New_York** (or run load immediately after extract to prove wiring — document wall-clock if you skip the window).

### C1. Daytime — extract assets

From orchestrator (replace table names if YAML differs):

```bash
ECR_URL=$(terraform output -raw ecr_framework_repository_url)  # run from laptop in infra/aws, or set on instance

# Small fixture
docker exec -w /workspace dagster dg launch --assets \
  'key:"nycdb2/nyc_housing/fixture_hello/extract/greetings"'

# Larger source (pick one for first POC pass; run both before calling Phase C complete)
docker exec -w /workspace dagster dg launch --assets \
  'key:"nycdb2/nyc_housing/rentstab_v2/extract/rentstab_v2"'

# Shapefile (requires ogr2ogr in image)
docker exec -w /workspace dagster dg launch --assets \
  'key:"nycdb2/nyc_housing/nycc/extract/nycc"'
```

Verify S3 landing:

```bash
BUCKET=$(terraform output -raw landing_bucket_name)
aws s3 ls "s3://${BUCKET}/extract/" --recursive | head
```

Record extract duration and approximate object sizes in your run log.

### C2. Overnight — load assets (+ dbt)

During **22:00–07:00 America/New_York** (or immediately after extract for wiring proof):

```bash
docker exec -w /workspace dagster dg launch --assets \
  'key:"nycdb2/nyc_housing/fixture_hello/load/greetings"'

docker exec -w /workspace dagster dg launch --assets \
  'key:"nycdb2/nyc_housing/rentstab_v2/load/rentstab_v2"'

docker exec -w /workspace dagster dg launch --assets \
  'key:"nycdb2/nyc_housing/nycc/load/nycc"'
```

Confirm in RDS (`psql` or Postico): tables in `nyc_housing` with expected row counts; load logs show server-side COPY (not full CSV download to EC2).

**dbt (included in Phase C):** after `fixture_hello` load:

```bash
docker exec -w /workspace dagster dg launch --assets \
  'key:"nycdb2/nyc_housing/dbt/fixture_greeting_count"'
```

**Derived docker (optional):** [`definitions.poc.yml`](https://github.com/JustFixNYC/opendata-etl/blob/main/examples/definitions.poc.yml) does not enable derived jobs (`nycdb2` has no `derived_python` jobs). Skip for POC subset, or add a derived-enabled repo to the manifest in a follow-up experiment.

**Phase C load done when:** all selected load assets **Succeeded** before **07:00 America/New_York** when using scheduled overnight runs; `extract_landing_exists` checks pass.

### C3. API smoke (API EC2)

Follow [First-time deploy — Part 7](aws-first-deploy.md#part-7--api-ec2-split-deploy) substeps **7.1–7.6** (ECR pull, read-role passwords, `api.env`, manifest mount, `docker run`, port-forward + curl).

After `fixture_hello` load:

```bash
curl -sS http://127.0.0.1:8000/healthz
curl -sS "http://127.0.0.1:8000/housing/hello/by-id?id=1"
```

Issue a key from your laptop (Part **7.6**) and retry with `Authorization: Bearer`.

---

## Validation log template

Copy into your PR or master plan run notes:

```text
Phase A: terraform apply YYYY-MM-DD — PASS/FAIL — notes:
Phase A: aws_s3 smoke — PASS/FAIL
Phase A: provision_roles — PASS/FAIL
Phase B: ECR + Dagster — PASS/FAIL
Phase B: API healthz — PASS/FAIL
Phase C: fixture_hello extract/load — start/end UTC — PASS/FAIL
Phase C: rentstab_v2 or nycc extract/load — start/end UTC — PASS/FAIL
Phase C: dbt fixture_greeting_count — PASS/FAIL
Phase C: API hello_by_id — PASS/FAIL
Overnight load before 07:00 America/New_York: YES/NO/N/A (manual run)
Blockers:
```

## Troubleshooting

| Symptom | Action |
|---------|--------|
| Empty Dagster asset list | Manifest path; git clone auth for `nycdb2` URL; run `dg check defs --no-check-yaml` |
| Extract OK, load fails S3 | [Bootstrap](aws-s3-copy-bootstrap.md); `OPENDATA_LOAD_BACKEND=s3_copy_rds`; `S3_BUCKET` set |
| `nycc` extract fails | Install/use image with GDAL; see [local development](../local-development.md) shapefile note |
| Load before extract | Run extract assets first; check `extract_landing_exists` |
| API 401/403 | Issue key with `opendata_nyc_housing_read`; set `OPENDATA_API_ROLE_DSNS` |
| `terraform plan` shows EKS | Wrong branch; use 19b tree (`modules/postgres_rds/`) |
| `invalid reference format` / `:poc` | `ECR_URL` empty — run `terraform output` from `infra/aws` (see Part 5) |

## Related

- [Deployment profiles](../deployment-profiles.md) — `standard` vs `lite`
- [First-time AWS deploy](aws-first-deploy.md) — detailed EC2/Docker steps
- Master plan Step 23 — handoff and 19b output table
