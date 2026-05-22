# Archived EKS module (Step 19)

This directory preserves the Step 19 **EKS** Terraform module (`cluster`, managed node group, IRSA worker role) removed in **Step 19b** for the JustFix parallel POC (`profile: standard` — EC2 orchestrator only, no Kubernetes).

To restore EKS for a future `profile: scaled` deployment:

1. Copy `*.tf` back to `infra/aws/modules/eks/`.
2. Re-wire `module "eks"` in `infra/aws/main.tf`, restore `eks_workers` security group, orchestrator EKS IAM, EKS outputs, and `tls` provider in `versions.tf`.
3. Re-add EKS variables to `variables.tf` and `terraform.tfvars.example`.

Active POC Terraform uses **RDS PostgreSQL** + **EC2 orchestrator** only. See [`../../../docs/deployment/aws-s3-copy-bootstrap.md`](../../../docs/deployment/aws-s3-copy-bootstrap.md).
