#!/bin/bash
# Orchestrator bootstrap (Option A): S3 runtime bundle + separate manifest + SSM env.
set -euo pipefail
exec > >(tee /var/log/opendata-orchestrator-bootstrap.log) 2>&1

export AWS_DEFAULT_REGION="${aws_region}"

INSTALL_DIR=/opt/opendata-etl
mkdir -p "$INSTALL_DIR" /var/lib/opendata-etl/dagster_home /var/lib/opendata-etl/definitions_work

echo "Installing Docker and Compose plugin..."
dnf install -y docker docker-compose-plugin
systemctl enable --now docker
usermod -aG docker ssm-user || true

echo "Fetching runtime bundle from ${runtime_bundle_s3_uri}..."
BUNDLE_ARCHIVE="$(mktemp)"
aws s3 cp "${runtime_bundle_s3_uri}" "$BUNDLE_ARCHIVE"
tar -xzf "$BUNDLE_ARCHIVE" -C "$INSTALL_DIR"
rm -f "$BUNDLE_ARCHIVE"

echo "Fetching manifest from ${manifest_s3_uri}..."
aws s3 cp "${manifest_s3_uri}" "$INSTALL_DIR/definitions.yml"
chmod 644 "$INSTALL_DIR/definitions.yml"

echo "Pulling framework image ${framework_image}..."
REGISTRY="${ecr_registry}"
aws ecr get-login-password --region "${aws_region}" | \
  docker login --username AWS --password-stdin "$REGISTRY"
docker pull "${framework_image}"

echo "Building .env from SSM..."
DB_PASSWORD="$(aws ssm get-parameter \
  --name "${master_password_ssm}" \
  --with-decryption \
  --query 'Parameter.Value' \
  --output text)"
STANDARD_ENV="$(aws ssm get-parameter \
  --name "${standard_env_ssm}" \
  --query 'Parameter.Value' \
  --output text)"

cat >"$INSTALL_DIR/.env" <<EOF
$STANDARD_ENV
OPENDATA_FRAMEWORK_IMAGE=${framework_image}
OPENDATA_DEFINITIONS_MANIFEST_PATH=$INSTALL_DIR/definitions.yml
OPENDATA_DEFINITIONS_WORK_DIR=/var/lib/opendata-etl/definitions_work
OPENDATA_DAGSTER_MATERIALIZE=full
OPENDATA_DAGSTER_DEFINITION_LOAD=clone
OPENDATA_S3_COPY_REGION=${aws_region}
DAGSTER_HOME=/var/lib/opendata-etl/dagster_home
DATABASE_URL=postgresql://${db_user}:$${DB_PASSWORD}@${db_endpoint}:5432/${db_name}?sslmode=require
EOF
chmod 600 "$INSTALL_DIR/.env"

echo "Starting Dagster via docker compose..."
cd "$INSTALL_DIR"
docker compose -f orchestrator-compose.yml --env-file .env up -d

echo "Orchestrator bootstrap complete."
