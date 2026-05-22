# SPDX-License-Identifier: AGPL-3.0-only
output "cluster_name" {
  value = aws_eks_cluster.this.name
}

output "cluster_endpoint" {
  value = aws_eks_cluster.this.endpoint
}

output "cluster_arn" {
  value = aws_eks_cluster.this.arn
}

output "oidc_provider_arn" {
  value = aws_iam_openid_connect_provider.eks.arn
}

output "worker_irsa_role_arn" {
  value = aws_iam_role.worker_irsa.arn
}

output "worker_irsa_role_name" {
  value = aws_iam_role.worker_irsa.name
}

output "node_role_arn" {
  value = aws_iam_role.node.arn
}
