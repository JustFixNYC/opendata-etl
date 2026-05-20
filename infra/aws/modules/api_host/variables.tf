# SPDX-License-Identifier: AGPL-3.0-only
variable "name_prefix" {
  type = string
}

variable "create" {
  type    = bool
  default = false
}

variable "instance_type" {
  type    = string
  default = "t3.small"
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
