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

output "aurora_cluster_endpoint" {
  description = "Aurora writer endpoint hostname."
  value       = module.aurora.cluster_endpoint
}

output "aurora_master_password_ssm" {
  description = "SSM parameter holding the generated master password (SecureString)."
  value       = module.aurora.master_password_ssm_parameter
  sensitive   = true
}

output "database_url_template_ssm" {
  value = module.aurora.database_url_template_ssm_parameter
}

output "eks_cluster_name" {
  value = module.eks.cluster_name
}

output "eks_cluster_endpoint" {
  value = module.eks.cluster_endpoint
}

output "eks_worker_irsa_role_arn" {
  description = "IAM role ARN for IRSA service account opendata-worker (Steps 21–22)."
  value       = module.eks.worker_irsa_role_arn
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

output "scaled_runtime_env_ssm" {
  description = "Reference SSM parameter listing scaled env flags."
  value       = "${local.ssm_prefix}/runtime/scaled_env"
}

output "smoke_check_commands" {
  description = "Post-apply smoke commands (run from a host with AWS CLI and network access)."
  value       = <<-EOT
    # Aurora (from orchestrator via SSM port-forward or psql client):
    aws ssm get-parameter --name ${module.aurora.master_password_ssm_parameter} --with-decryption --query Parameter.Value --output text
    psql "$(aws ssm get-parameter --name ${module.aurora.database_url_template_ssm_parameter} --query Parameter.Value --output text)"

    # EKS:
    aws eks update-kubeconfig --name ${module.eks.cluster_name} --region ${var.aws_region}
    kubectl get nodes

    # S3 landing:
    aws s3 ls s3://${module.landing.bucket_id}/extract/
  EOT
}
