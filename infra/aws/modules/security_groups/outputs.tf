# SPDX-License-Identifier: AGPL-3.0-only
output "aurora_security_group_id" {
  value = aws_security_group.aurora.id
}

output "orchestrator_security_group_id" {
  value = aws_security_group.orchestrator.id
}

output "api_security_group_id" {
  value = aws_security_group.api.id
}

output "eks_workers_security_group_id" {
  value = aws_security_group.eks_workers.id
}
