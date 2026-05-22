# SPDX-License-Identifier: AGPL-3.0-only
output "cluster_id" {
  value = aws_rds_cluster.this.id
}

output "cluster_arn" {
  value = aws_rds_cluster.this.arn
}

output "cluster_endpoint" {
  value = aws_rds_cluster.this.endpoint
}

output "cluster_reader_endpoint" {
  value = aws_rds_cluster.this.reader_endpoint
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
