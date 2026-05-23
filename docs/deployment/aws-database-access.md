# AWS database access (RDS via SSM)

The parallel POC **RDS PostgreSQL** instance has **no public IP**. Operators reach it through **SSM Session Manager** on the orchestrator EC2, using port forwarding to a local port (recommended for **Postico** and `psql` on a laptop).

## Prerequisites

- AWS CLI v2 and [Session Manager plugin](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html)
- Terraform applied; outputs available from `infra/aws/`
- IAM permission for `ssm:StartSession` on the orchestrator instance

## Port forward (Postico / local psql)

```bash
cd infra/aws

INSTANCE_ID=$(terraform output -raw orchestrator_instance_id)
DB_HOST=$(terraform output -raw database_endpoint)
LOCAL_PORT=15432

aws ssm start-session \
  --target "$INSTANCE_ID" \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters "{\"host\":[\"$DB_HOST\"],\"portNumber\":[\"5432\"],\"localPortNumber\":[\"$LOCAL_PORT\"]}"
```

Keep this terminal open while connected.

### Postico

| Field | Value |
|-------|--------|
| Host | `127.0.0.1` |
| Port | `15432` |
| User | `opendata_admin` |
| Database | `opendata` |
| SSL | **Require** |

Password (do not commit or paste into tickets):

```bash
aws ssm get-parameter \
  --name "$(terraform output -raw master_password_ssm)" \
  --with-decryption --query Parameter.Value --output text
```

### psql on laptop

```bash
export PGPASSWORD="$(aws ssm get-parameter \
  --name "$(terraform output -raw master_password_ssm)" \
  --with-decryption --query Parameter.Value --output text)"

psql "host=127.0.0.1 port=15432 dbname=opendata user=opendata_admin sslmode=require"
```

## psql on orchestrator EC2

```bash
aws ssm start-session --target "$(terraform output -raw orchestrator_instance_id)"
# On the instance:
export PGPASSWORD="$(aws ssm get-parameter \
  --name /opendata-etl/poc/postgres/master_password \
  --with-decryption --query Parameter.Value --output text)"
psql "host=$(terraform output -raw database_endpoint) dbname=opendata user=opendata_admin sslmode=require"
```

Adjust the SSM path if you changed `project_name` or `environment` in `terraform.tfvars`.

## Security notes

- Do not expose RDS with a public security group rule for operator convenience.
- Rotate the master password via RDS modify + SSM update + restart orchestrator/API containers (see [aws-maintenance.md](aws-maintenance.md)).
- API and orchestrator hosts reach RDS on port 5432 via security group rules only (no bastion SSH required).

## Related

- [S3 COPY bootstrap](aws-s3-copy-bootstrap.md) — PostGIS and `aws_s3` extensions
- [infra/aws/README.md](https://github.com/JustFixNYC/opendata-etl/blob/main/infra/aws/README.md) — Terraform outputs and smoke commands
