# SPDX-License-Identifier: AGPL-3.0-only
output "framework_repository_url" {
  value = aws_ecr_repository.framework.repository_url
}

output "derived_repository_url" {
  value = aws_ecr_repository.derived.repository_url
}

output "framework_repository_arn" {
  value = aws_ecr_repository.framework.arn
}

output "derived_repository_arn" {
  value = aws_ecr_repository.derived.arn
}
