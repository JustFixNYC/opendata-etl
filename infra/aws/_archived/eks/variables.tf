# SPDX-License-Identifier: AGPL-3.0-only
variable "name_prefix" {
  type = string
}

variable "ssm_prefix" {
  type = string
}

variable "cluster_version" {
  type    = string
  default = "1.31"
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "public_subnet_ids" {
  type = list(string)
}

variable "worker_security_group_id" {
  type        = string
  description = "Security group attached to EKS worker nodes (batch Jobs)."
}

variable "node_instance_types" {
  type    = list(string)
  default = ["m6i.large"]
}

variable "node_desired_size" {
  type    = number
  default = 2
}

variable "node_min_size" {
  type    = number
  default = 1
}

variable "node_max_size" {
  type    = number
  default = 10
}

variable "landing_bucket_arn" {
  type = string
}

variable "kubernetes_namespace" {
  type    = string
  default = "opendata-etl"
}

variable "worker_service_account_name" {
  type    = string
  default = "opendata-worker"
}
