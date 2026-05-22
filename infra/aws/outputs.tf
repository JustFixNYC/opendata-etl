# SPDX-License-Identifier: AGPL-3.0-only
output "vpc_id" {
  description = "VPC identifier."
  value       = module.network.vpc_id
}

output "landing_bucket_name" {
  description = "S3 landing bucket (extract/ and derived/ prefixes)."
  value       = module.landing.bucket_id
}

output "landing_bucket_arn" {
  value = module.landing.bucket_arn
}

output "database_endpoint" {
  description = "RDS PostgreSQL hostname."
  value       = module.postgres_rds.instance_endpoint
}

output "database_instance_identifier" {
  description = "RDS instance identifier for AWS CLI."
  value       = module.postgres_rds.instance_identifier
}

output "master_password_ssm" {
  description = "SSM parameter holding the generated master password (SecureString)."
  value       = module.postgres_rds.master_password_ssm_parameter
  sensitive   = true
}

output "database_url_template_ssm" {
  value = module.postgres_rds.database_url_template_ssm_parameter
}

output "rds_s3_import_role_arn" {
  description = "IAM role associated with RDS for S3 import (aws_s3)."
  value       = module.postgres_rds.s3_import_role_arn
}

output "ecr_framework_repository_url" {
  value = module.ecr.framework_repository_url
}

output "ecr_derived_repository_url" {
  value = module.ecr.derived_repository_url
}

output "orchestrator_instance_id" {
  value = module.orchestrator.instance_id
}

output "orchestrator_private_ip" {
  value = module.orchestrator.private_ip
}

output "api_instance_id" {
  value = module.api_host.instance_id
}

output "ssm_parameter_prefix" {
  value = local.ssm_prefix
}

output "standard_runtime_env_ssm" {
  description = "Reference SSM parameter listing standard-profile env flags."
  value       = "${local.ssm_prefix}/runtime/standard_env"
}

output "smoke_check_commands" {
  description = "Post-apply smoke commands (run from a host with AWS CLI and SSM plugin)."
  value       = <<-EOT
    # Master password (do not paste into tickets):
    aws ssm get-parameter --name ${module.postgres_rds.master_password_ssm_parameter} --with-decryption --query Parameter.Value --output text

    # SSM port forward for Postico/psql (keep session open):
    aws ssm start-session --target ${module.orchestrator.instance_id} \
      --document-name AWS-StartPortForwardingSessionToRemoteHost \
      --parameters '{"host":["${module.postgres_rds.instance_endpoint}"],"portNumber":["5432"],"localPortNumber":["15432"]}'

    # Then: psql "postgresql://opendata_admin:<password>@127.0.0.1:15432/opendata?sslmode=require"

    # S3 landing:
    aws s3 ls s3://${module.landing.bucket_id}/extract/

    # See docs/deployment/aws-s3-copy-bootstrap.md for aws_s3 import smoke SQL.
  EOT
}
