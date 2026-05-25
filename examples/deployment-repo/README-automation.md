# Standard-profile orchestrator automation (OSS sample)

Step **26f** bootstraps the reference **orchestrator EC2** from **two S3 objects** plus SSM env — no `git clone` and no manual `docker run` on the instance.

| Artifact | Contents | Typical key |
| -------- | -------- | ----------- |
| **Runtime bundle** (`.tar.gz`) | `orchestrator-compose.yml`, `env.orchestrator.example` only | `s3://<landing>/config/orchestrator-runtime.tar.gz` |
| **Manifest** (plain YAML) | `definitions.poc.yml` (or prod) | `s3://<landing>/config/definitions.yml` |

The manifest is **never** inside the runtime tarball so you can update datasets without rebuilding the bundle.

## Build and upload (operator)

From the framework repo root, after `terraform apply` (or with any test bucket). If you copied this
template into a deployment repo, set `RUNTIME_DIR` to that repo's `runtime/` path:

```bash
# 1) Build runtime tarball (no definitions*.yml)
RUNTIME_DIR=/path/to/deployment-repo/runtime ./scripts/build-runtime-bundle.sh /tmp/orchestrator-runtime.tar.gz

# 2) Resolve S3 targets (defaults match infra/aws locals)
cd infra/aws
BUNDLE_URI=$(terraform output -raw orchestrator_runtime_bundle_s3_uri)
MANIFEST_URI=$(terraform output -raw orchestrator_manifest_s3_uri)
cd ../..

# 3) Upload both objects
aws s3 cp /tmp/orchestrator-runtime.tar.gz "$BUNDLE_URI"
aws s3 cp /path/to/deployment-repo/definitions.poc.yml "$MANIFEST_URI"
```

**Dry-run with a test bucket** (no Terraform):

```bash
export TEST_BUCKET=my-opendata-config-test
aws s3 mb "s3://${TEST_BUCKET}" 2>/dev/null || true
./scripts/build-runtime-bundle.sh /tmp/orchestrator-runtime.tar.gz
aws s3 cp /tmp/orchestrator-runtime.tar.gz "s3://${TEST_BUCKET}/config/orchestrator-runtime.tar.gz"
aws s3 cp /path/to/deployment-repo/definitions.poc.yml "s3://${TEST_BUCKET}/config/definitions.yml"
aws s3 ls "s3://${TEST_BUCKET}/config/"
```

Wire custom URIs in `infra/aws/terraform.tfvars`:

```hcl
orchestrator_runtime_bundle_s3_uri = "s3://my-opendata-config/config/orchestrator-runtime.tar.gz"
orchestrator_manifest_s3_uri       = "s3://my-opendata-config/config/definitions.yml"
```

The orchestrator instance profile must be allowed `s3:GetObject` on those objects (default Terraform grants read/write on the **landing** bucket).

## Boot sequence (user_data)

On first boot the instance:

1. Installs Docker and the Compose plugin
2. `aws s3 cp` runtime bundle → extracts under `/opt/opendata-etl/`
3. `aws s3 cp` manifest → `/opt/opendata-etl/definitions.yml`
4. ECR login + `docker pull` for `orchestrator_framework_image`
5. Builds `/opt/opendata-etl/.env` from SSM `.../runtime/standard_env` + RDS password + `DATABASE_URL`
6. `docker compose -f orchestrator-compose.yml up -d`

Logs: `/var/log/opendata-orchestrator-bootstrap.log` on the instance.

## Order of operations

1. `terraform apply` (creates bucket, SSM, EC2)
2. Push framework image to ECR (see [aws-first-deploy.md](../../docs/deployment/aws-first-deploy.md) Part 5)
3. **Upload runtime bundle + manifest** (this doc)
4. If the instance already booted without objects, replace it or re-run bootstrap:

```bash
INSTANCE_ID=$(terraform -chdir=infra/aws output -raw orchestrator_instance_id)
aws ec2 reboot-instances --instance-ids "$INSTANCE_ID"
# user_data runs only on first launch; for replacement:
# terraform apply -replace='module.orchestrator.aws_instance.orchestrator[0]'
```

Prefer uploading **before** the first orchestrator launch when possible.

## Runtime files in this tree

- [`runtime/orchestrator-compose.yml`](runtime/orchestrator-compose.yml) — Dagster service (docker.sock for derived jobs)
- [`runtime/env.orchestrator.example`](runtime/env.orchestrator.example) — documentation template (live `.env` is rendered from SSM at boot)
- [`runtime/api-compose.yml`](runtime/api-compose.yml) and [`runtime/env.api.example`](runtime/env.api.example) — API host shape; automated API bootstrap lands in a follow-up.
