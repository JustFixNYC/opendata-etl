# SPDX-License-Identifier: AGPL-3.0-only
output "instance_id" {
  value = aws_db_instance.this.id
}

output "instance_identifier" {
  description = "RDS instance identifier (for aws rds describe-db-instances)."
  value       = aws_db_instance.this.identifier
}

output "instance_arn" {
  value = aws_db_instance.this.arn
}

output "instance_endpoint" {
  description = "RDS hostname (use for DATABASE_URL and SSM port forward target)."
  value       = aws_db_instance.this.address
}

output "database_name" {
  value = var.database_name
}

output "master_username" {
  value = var.master_username
}

output "master_password_ssm_parameter" {
  value = aws_ssm_parameter.master_password.name
}

output "database_url_template_ssm_parameter" {
  value = aws_ssm_parameter.database_url_template.name
}

output "s3_import_role_arn" {
  value = aws_iam_role.s3_import.arn
}
