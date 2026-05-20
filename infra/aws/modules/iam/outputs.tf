# SPDX-License-Identifier: AGPL-3.0-only
output "orchestrator_role_arn" {
  value = aws_iam_role.orchestrator.arn
}

output "orchestrator_instance_profile_name" {
  value = aws_iam_instance_profile.orchestrator.name
}

output "api_role_arn" {
  value = aws_iam_role.api.arn
}

output "api_instance_profile_name" {
  value = aws_iam_instance_profile.api.name
}

output "definitions_manifest_ssm_parameter" {
  value = aws_ssm_parameter.definitions_manifest.name
}
