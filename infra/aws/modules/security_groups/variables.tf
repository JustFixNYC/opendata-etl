# SPDX-License-Identifier: AGPL-3.0-only
variable "name_prefix" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "admin_cidr_blocks" {
  type    = list(string)
  default = []
}

variable "api_ingress_cidr_blocks" {
  type    = list(string)
  default = ["0.0.0.0/0"]
}
