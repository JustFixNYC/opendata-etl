terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

module "opendata_etl_aws" {
  source = "github.com/example-org/opendata-etl//infra/aws?ref=v0.1.0"

  project_name = var.project_name
  environment  = var.environment
  aws_region   = var.aws_region

  admin_cidr_blocks       = var.admin_cidr_blocks
  api_ingress_cidr_blocks = var.api_ingress_cidr_blocks

  postgres_instance_class     = var.postgres_instance_class
  landing_bucket_force_destroy = var.landing_bucket_force_destroy
  single_nat_gateway           = var.single_nat_gateway

  create_orchestrator_instance = true
  create_api_instance          = true

  orchestrator_runtime_bundle_s3_uri = var.orchestrator_runtime_bundle_s3_uri
  orchestrator_manifest_s3_uri       = var.orchestrator_manifest_s3_uri
  orchestrator_framework_image       = var.orchestrator_framework_image

  tags = var.tags
}

variable "project_name" {
  type    = string
  default = "opendata-etl"
}

variable "environment" {
  type    = string
  default = "poc"
}

variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "admin_cidr_blocks" {
  type = list(string)
}

variable "api_ingress_cidr_blocks" {
  type    = list(string)
  default = []
}

variable "postgres_instance_class" {
  type    = string
  default = "db.t4g.medium"
}

variable "landing_bucket_force_destroy" {
  type    = bool
  default = false
}

variable "single_nat_gateway" {
  type    = bool
  default = true
}

variable "orchestrator_runtime_bundle_s3_uri" {
  type    = string
  default = ""
}

variable "orchestrator_manifest_s3_uri" {
  type    = string
  default = ""
}

variable "orchestrator_framework_image" {
  type    = string
  default = ""
}

variable "tags" {
  type    = map(string)
  default = {}
}

output "landing_bucket_name" {
  value = module.opendata_etl_aws.landing_bucket_name
}

output "database_endpoint" {
  value = module.opendata_etl_aws.database_endpoint
}

output "orchestrator_instance_id" {
  value = module.opendata_etl_aws.orchestrator_instance_id
}

output "api_instance_id" {
  value = module.opendata_etl_aws.api_instance_id
}
