# SPDX-License-Identifier: AGPL-3.0-only
locals {
  name_prefix = "${var.project_name}-${var.environment}"

  ssm_prefix = var.ssm_parameter_prefix != "" ? var.ssm_parameter_prefix : "/${var.project_name}/${var.environment}"

  orchestrator_runtime_bundle_s3_uri = (
    var.orchestrator_runtime_bundle_s3_uri != ""
    ? var.orchestrator_runtime_bundle_s3_uri
    : "s3://${module.landing.bucket_id}/config/orchestrator-runtime.tar.gz"
  )

  orchestrator_manifest_s3_uri = (
    var.orchestrator_manifest_s3_uri != ""
    ? var.orchestrator_manifest_s3_uri
    : "s3://${module.landing.bucket_id}/config/definitions.yml"
  )

  orchestrator_framework_image = (
    var.orchestrator_framework_image != ""
    ? var.orchestrator_framework_image
    : "${module.ecr.framework_repository_url}:poc"
  )

  orchestrator_ecr_registry = regex("^[^/]+", local.orchestrator_framework_image)
}
