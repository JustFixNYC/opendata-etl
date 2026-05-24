# SPDX-License-Identifier: AGPL-3.0-only
variable "name_prefix" {
  type = string
}

variable "create" {
  type    = bool
  default = true
}

variable "instance_type" {
  type    = string
  default = "t3.large"
}

variable "subnet_id" {
  type = string
}

variable "security_group_id" {
  type = string
}

variable "instance_profile_name" {
  type = string
}

variable "aws_region" {
  type        = string
  description = "AWS region (ECR login and OPENDATA_S3_COPY_REGION)."
}

variable "runtime_bundle_s3_uri" {
  type        = string
  description = "S3 URI of orchestrator runtime tarball (compose + env template only)."
}

variable "manifest_s3_uri" {
  type        = string
  description = "S3 URI of definitions manifest (separate object from runtime bundle)."
}

variable "framework_image" {
  type        = string
  description = "Full container image reference including tag (ECR or GHCR)."
}

variable "ecr_registry" {
  type        = string
  description = "Docker registry host for ECR login (e.g. 123456789.dkr.ecr.us-east-1.amazonaws.com)."
}

variable "standard_env_ssm" {
  type        = string
  description = "SSM parameter name for standard-profile env flags (String)."
}

variable "master_password_ssm" {
  type        = string
  description = "SSM SecureString parameter name for RDS master password."
}

variable "db_user" {
  type = string
}

variable "db_endpoint" {
  type = string
}

variable "db_name" {
  type = string
}
