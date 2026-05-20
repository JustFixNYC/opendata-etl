# SPDX-License-Identifier: AGPL-3.0-only
variable "name_prefix" {
  type = string
}

variable "ssm_prefix" {
  type = string
}

variable "bucket_name" {
  type        = string
  description = "Globally unique S3 bucket name for extract/ and derived/ prefixes."
}

variable "force_destroy" {
  type    = bool
  default = false
}

variable "lifecycle_expire_days" {
  type    = number
  default = 90
}
