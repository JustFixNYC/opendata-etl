# SPDX-License-Identifier: AGPL-3.0-only
variable "name_prefix" {
  type = string
}

variable "ssm_prefix" {
  type = string
}

variable "landing_bucket_arn" {
  type = string
}

variable "landing_bucket_id" {
  type = string
}

variable "postgres_table_owner_role" {
  type        = string
  description = "Postgres role that owns loaded tables (RDS master user on POC)."
}
