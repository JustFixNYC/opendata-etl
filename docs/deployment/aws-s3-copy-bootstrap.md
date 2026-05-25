# AWS RDS bootstrap for server-side COPY (S3 → RDS)

One-time setup on the **parallel POC** RDS instance after `terraform apply` (Step 19b). Required before Step 20 `OPENDATA_LOAD_BACKEND=s3_copy_rds` integration smoke.

**Prerequisites:** Terraform outputs recorded (`database_endpoint`, `master_password_ssm`, `landing_bucket_name`, `orchestrator_instance_id`). RDS S3 import IAM role is created by Terraform (`rds_s3_import_role_arn` output).

## 1. Connect to RDS

Use SSM port forwarding from your laptop — see [Database access](aws-database-access.md). Or open a shell on the orchestrator EC2 via Session Manager and use `psql` with the private endpoint.

```bash
cd infra/aws
export PGPASSWORD="$(aws ssm get-parameter \
  --name "$(terraform output -raw master_password_ssm)" \
  --with-decryption --query Parameter.Value --output text)"

psql "host=127.0.0.1 port=15432 dbname=opendata user=opendata_admin sslmode=require"
```

## 2. Enable extensions

Run as the master user (`opendata_admin`):

```sql
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS aws_commons;
CREATE EXTENSION IF NOT EXISTS aws_s3;
```

Verify:

```sql
SELECT extname FROM pg_extension
WHERE extname IN ('postgis', 'aws_commons', 'aws_s3');
```

## 3. Verify RDS S3 import IAM association

From your workstation (not SQL):

```bash
aws rds describe-db-instances \
  --db-instance-identifier "$(terraform output -raw database_instance_identifier)" \
  --query 'DBInstances[0].AssociatedRoles' \
  --output table
```

You should see a role with `FeatureName` = `s3Import`. The role ARN matches `terraform output -raw rds_s3_import_role_arn`.

## 4. S3 import smoke test

Upload a tiny CSV to the landing bucket (replace bucket name from `terraform output -raw landing_bucket_name`):

```bash
BUCKET="$(terraform output -raw landing_bucket_name)"
echo "id,name
1,alpha
2,beta" > /tmp/smoke.csv
aws s3 cp /tmp/smoke.csv "s3://${BUCKET}/extract/smoke-test/2026-05-22/rows.csv"
```

In `psql`:

```sql
CREATE TABLE IF NOT EXISTS public._s3_import_smoke (
  id   integer,
  name text
);

TRUNCATE public._s3_import_smoke;

SELECT aws_s3.table_import_from_s3(
  'public._s3_import_smoke',
  'id,name',
  '(format csv, header true)',
  aws_commons.create_s3_uri(
    'REPLACE_BUCKET',
    'extract/smoke-test/2026-05-22/rows.csv',
    'us-east-1'
  )
);

SELECT * FROM public._s3_import_smoke;
```

Replace `REPLACE_BUCKET` and region to match your deployment.

Expected: two rows. On failure, check IAM role association, bucket policy (Terraform attaches one for the import role), and that the object key exists.

## 5. Framework role provisioning

Run on your **laptop** from the framework repo root (with venv / `pip install -e ".[dev]"`). The orchestrator EC2 does not ship Python or this repo — use SSM port forward (see [Database access](aws-database-access.md)) so RDS is reachable at `127.0.0.1:15432` while the forward session is open.

```bash
cd infra/aws
export PGPASSWORD="$(aws ssm get-parameter \
  --name "$(terraform output -raw master_password_ssm)" \
  --with-decryption --query Parameter.Value --output text)"
export DATABASE_URL="postgresql://opendata_admin:${PGPASSWORD}@127.0.0.1:15432/opendata?sslmode=require"

cd ../..
export OPENDATA_PG_OWNER_ROLE=opendata_admin
python scripts/provision_roles.py \
  --manifest /path/to/deployment-repo/definitions.poc.yml \
  --table-owner-role opendata_admin
```

- CLI flag is **`--manifest`**, not `--definitions`.
- **Table owner role:** Lite Docker uses `opendata`; RDS POC only has the Terraform master user (`opendata_admin` by default). Pass **`--table-owner-role opendata_admin`** (and set `OPENDATA_PG_OWNER_ROLE` for later loads) so `CREATE SCHEMA ... AUTHORIZATION` succeeds.
- Deployment repo **`definitions.poc.yml`** — `profile: standard` with the operator's POC dataset subset ([first-time deploy](aws-first-deploy.md)).
- If RDS is reachable without port forward (e.g. from orchestrator after you install Python there), set `DATABASE_URL` with `terraform output -raw database_endpoint` as the host instead of `127.0.0.1`.

## Troubleshooting

| Symptom | Check |
|--------|--------|
| `role "opendata" does not exist` | Use `--table-owner-role opendata_admin` (RDS master user), not lite default `opendata` |
| `aws_s3` extension missing | Engine version 16.x; run bootstrap SQL as master |
| `permission denied` on S3 import | `aws_db_instance_role_association` + IAM role policy + bucket policy |
| Timeout from private VPC | NAT gateway for orchestrator; optional S3 VPC gateway endpoint |
| SSL errors from Postico | SSL mode **Require**; use port forward target `127.0.0.1:15432` |

## 6. Framework load backend (Step 20)

On the orchestrator (or laptop with SSM port forward), set:

```bash
export OPENDATA_LANDING_BACKEND=s3
export OPENDATA_LOAD_BACKEND=s3_copy_rds
export OPENDATA_S3_COPY_REGION=us-east-1   # match landing bucket region
export S3_BUCKET="$(terraform output -raw landing_bucket_name)"
# DATABASE_URL as in section 5
```

Materialize a small dataset whose extract landed under `extract/` in the landing bucket. The framework calls `aws_s3.table_import_from_s3` inside RDS — CSV bytes do not stream through the Dagster host.

Optional pytest smoke (after uploading a CSV to the landing bucket):

```bash
export OPENDATA_S3_COPY_RDS_SMOKE=1
export OPENDATA_S3_COPY_SMOKE_BUCKET="$BUCKET"
export OPENDATA_S3_COPY_SMOKE_KEY="extract/smoke-test/2026-05-22/rows.csv"
pytest tests/test_s3_copy_rds.py::test_s3_copy_rds_aws_smoke -q
```

## Next steps

- [Parallel POC validation runbook](aws-poc-validation.md) — Phases A–C (Terraform through first split materialization)
- [First-time AWS deploy](aws-first-deploy.md) — EC2 Docker deploy (Phase B)
