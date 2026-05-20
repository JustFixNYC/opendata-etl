# SPDX-License-Identifier: AGPL-3.0-only
locals {
  name_prefix = "${var.project_name}-${var.environment}"

  ssm_prefix = var.ssm_parameter_prefix != "" ? var.ssm_parameter_prefix : "/${var.project_name}/${var.environment}"
}
