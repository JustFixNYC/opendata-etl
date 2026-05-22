# SPDX-License-Identifier: AGPL-3.0-only
output "postgres_security_group_id" {
  value = aws_security_group.postgres.id
}

output "orchestrator_security_group_id" {
  value = aws_security_group.orchestrator.id
}

output "api_security_group_id" {
  value = aws_security_group.api.id
}
