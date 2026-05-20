# SPDX-License-Identifier: AGPL-3.0-only
variable "project_name" {
  type        = string
  description = "Short name used in resource names and SSM paths."
  default     = "opendata-etl"
}

variable "environment" {
  type        = string
  description = "Deployment environment label (e.g. prod, staging)."
  default     = "prod"
}

variable "aws_region" {
  type        = string
  description = "AWS region for all resources."
  default     = "us-east-1"
}

variable "vpc_cidr" {
  type        = string
  description = "VPC CIDR block."
  default     = "10.20.0.0/16"
}

variable "single_nat_gateway" {
  type        = bool
  description = "Use one NAT gateway for cost savings (non-HA egress)."
  default     = true
}

variable "admin_cidr_blocks" {
  type        = list(string)
  description = "CIDR blocks allowed to reach Dagster UI (port 3000) and SSH if enabled."
  default     = []
}

variable "api_ingress_cidr_blocks" {
  type        = list(string)
  description = "CIDR blocks allowed to reach the API load balancer / host (80/443)."
  default     = ["0.0.0.0/0"]
}

variable "aurora_engine_version" {
  type        = string
  description = "Aurora PostgreSQL engine version."
  default     = "16.4"
}

variable "aurora_instance_class" {
  type        = string
  description = "Aurora instance class for the writer (and readers if enabled)."
  default     = "db.r6g.large"
}

variable "aurora_database_name" {
  type        = string
  description = "Initial database name on the Aurora cluster."
  default     = "opendata"
}

variable "aurora_master_username" {
  type        = string
  description = "Master username for Aurora (password generated and stored in SSM)."
  default     = "opendata_admin"
}

variable "aurora_backup_retention_days" {
  type        = number
  description = "Aurora backup retention in days."
  default     = 7
}

variable "landing_bucket_force_destroy" {
  type        = bool
  description = "Allow Terraform to destroy a non-empty landing bucket (dev only)."
  default     = false
}

variable "landing_lifecycle_expire_days" {
  type        = number
  description = "Expire objects under extract/ and derived/ after this many days (0 = disabled)."
  default     = 90
}

variable "eks_cluster_version" {
  type        = string
  description = "EKS control plane version."
  default     = "1.31"
}

variable "eks_node_instance_types" {
  type        = list(string)
  description = "Instance types for the EKS managed node group running extract/derived Jobs."
  default     = ["m6i.large"]
}

variable "eks_node_desired_size" {
  type        = number
  description = "Desired node count for EKS Job workers."
  default     = 2
}

variable "eks_node_min_size" {
  type        = number
  default     = 1
}

variable "eks_node_max_size" {
  type        = number
  default     = 10
}

variable "create_orchestrator_instance" {
  type        = bool
  description = "Provision a reference EC2 Dagster orchestrator (recommended reference path)."
  default     = true
}

variable "orchestrator_instance_type" {
  type        = string
  description = "EC2 instance type for the Dagster orchestrator."
  default     = "t3.large"
}

variable "create_api_instance" {
  type        = bool
  description = "Provision a reference EC2 API host (split from orchestrator)."
  default     = false
}

variable "api_instance_type" {
  type        = string
  default     = "t3.small"
}

variable "ssm_parameter_prefix" {
  type        = string
  description = "Prefix for SSM Parameter Store secrets (no leading slash)."
  default     = ""
}

variable "tags" {
  type        = map(string)
  description = "Additional resource tags."
  default     = {}
}
