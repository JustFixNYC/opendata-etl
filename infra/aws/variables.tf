# SPDX-License-Identifier: AGPL-3.0-only
variable "project_name" {
  type        = string
  description = "Short name used in resource names and SSM paths."
  default     = "opendata-etl"
}

variable "environment" {
  type        = string
  description = "Deployment environment label (e.g. poc, prod)."
  default     = "poc"
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

variable "postgres_engine_version" {
  type        = string
  description = "RDS PostgreSQL engine version."
  default     = "16.6"
}

variable "postgres_instance_class" {
  type        = string
  description = "RDS instance class (POC default db.t4g.medium)."
  default     = "db.t4g.medium"
}

variable "postgres_allocated_storage" {
  type        = number
  description = "Initial allocated storage in GB."
  default     = 20
}

variable "postgres_max_allocated_storage" {
  type        = number
  description = "Maximum autoscaling storage in GB."
  default     = 100
}

variable "postgres_database_name" {
  type        = string
  description = "Initial database name on the RDS instance."
  default     = "opendata"
}

variable "postgres_master_username" {
  type        = string
  description = "Master username for RDS (password generated and stored in SSM)."
  default     = "opendata_admin"
}

variable "postgres_backup_retention_days" {
  type        = number
  description = "RDS backup retention in days."
  default     = 7
}

variable "postgres_deletion_protection" {
  type        = bool
  description = "Enable deletion protection on the RDS instance."
  default     = true
}

variable "postgres_skip_final_snapshot" {
  type        = bool
  description = "Skip final snapshot on destroy (set true only for ephemeral POC)."
  default     = false
}

variable "landing_bucket_force_destroy" {
  type        = bool
  description = "Allow Terraform to destroy a non-empty landing bucket (dev/POC only)."
  default     = false
}

variable "landing_lifecycle_expire_days" {
  type        = number
  description = "Expire objects under extract/ and derived/ after this many days (0 = disabled)."
  default     = 90
}

variable "create_orchestrator_instance" {
  type        = bool
  description = "Provision a reference EC2 Dagster orchestrator."
  default     = true
}

variable "orchestrator_instance_type" {
  type        = string
  description = "EC2 instance type for the Dagster orchestrator."
  default     = "t3.large"
}

variable "orchestrator_runtime_bundle_s3_uri" {
  type        = string
  description = "S3 URI of orchestrator runtime tarball (compose + env template only). Empty = landing bucket config/orchestrator-runtime.tar.gz."
  default     = ""
}

variable "orchestrator_manifest_s3_uri" {
  type        = string
  description = "S3 URI of definitions manifest (separate from runtime bundle). Empty = landing bucket config/definitions.yml."
  default     = ""
}

variable "orchestrator_framework_image" {
  type        = string
  description = "Full ECR/GHCR image reference including tag. Empty = ecr_framework_repository_url:poc."
  default     = ""
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
