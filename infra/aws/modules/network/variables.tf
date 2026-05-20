# SPDX-License-Identifier: AGPL-3.0-only
variable "name_prefix" {
  type = string
}

variable "vpc_cidr" {
  type = string
}

variable "single_nat_gateway" {
  type    = bool
  default = true
}
