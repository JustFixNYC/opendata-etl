# SPDX-License-Identifier: AGPL-3.0-only
# Reference Terraform for profile: standard (RDS PostgreSQL + S3 landing + EC2 orchestrator).
# Step 19b removed EKS; archived under _archived/eks/. See docs/deployment/aws-s3-copy-bootstrap.md.

module "network" {
  source = "./modules/network"

  name_prefix        = local.name_prefix
  vpc_cidr           = var.vpc_cidr
  single_nat_gateway = var.single_nat_gateway
}

module "security_groups" {
  source = "./modules/security_groups"

  name_prefix             = local.name_prefix
  vpc_id                  = module.network.vpc_id
  admin_cidr_blocks       = var.admin_cidr_blocks
  api_ingress_cidr_blocks = var.api_ingress_cidr_blocks
}

module "landing" {
  source = "./modules/landing"

  name_prefix           = local.name_prefix
  ssm_prefix            = local.ssm_prefix
  bucket_name           = "${local.name_prefix}-landing-${data.aws_caller_identity.current.account_id}"
  force_destroy         = var.landing_bucket_force_destroy
  lifecycle_expire_days = var.landing_lifecycle_expire_days
}

module "postgres_rds" {
  source = "./modules/postgres_rds"

  name_prefix          = local.name_prefix
  ssm_prefix           = local.ssm_prefix
  private_subnet_ids   = module.network.private_subnet_ids
  security_group_id    = module.security_groups.postgres_security_group_id
  landing_bucket_arn    = module.landing.bucket_arn
  landing_bucket_id     = module.landing.bucket_id
  engine_version       = var.postgres_engine_version
  instance_class       = var.postgres_instance_class
  allocated_storage    = var.postgres_allocated_storage
  max_allocated_storage = var.postgres_max_allocated_storage
  database_name        = var.postgres_database_name
  master_username      = var.postgres_master_username
  backup_retention_days = var.postgres_backup_retention_days
  deletion_protection  = var.postgres_deletion_protection
  skip_final_snapshot  = var.postgres_skip_final_snapshot
}

module "ecr" {
  source = "./modules/ecr"

  name_prefix = local.name_prefix
}

module "iam" {
  source = "./modules/iam"

  name_prefix               = local.name_prefix
  ssm_prefix                = local.ssm_prefix
  landing_bucket_arn        = module.landing.bucket_arn
  landing_bucket_id         = module.landing.bucket_id
  postgres_table_owner_role = var.postgres_master_username
}

module "orchestrator" {
  source = "./modules/orchestrator"

  name_prefix             = local.name_prefix
  create                  = var.create_orchestrator_instance
  instance_type           = var.orchestrator_instance_type
  subnet_id               = module.network.private_subnet_ids[0]
  security_group_id       = module.security_groups.orchestrator_security_group_id
  instance_profile_name   = module.iam.orchestrator_instance_profile_name
  aws_region              = var.aws_region
  runtime_bundle_s3_uri   = local.orchestrator_runtime_bundle_s3_uri
  manifest_s3_uri         = local.orchestrator_manifest_s3_uri
  framework_image         = local.orchestrator_framework_image
  ecr_registry            = local.orchestrator_ecr_registry
  standard_env_ssm        = "${local.ssm_prefix}/runtime/standard_env"
  master_password_ssm     = module.postgres_rds.master_password_ssm_parameter
  db_user                 = var.postgres_master_username
  db_endpoint             = module.postgres_rds.instance_endpoint
  db_name                 = var.postgres_database_name
}

module "api_host" {
  source = "./modules/api_host"

  name_prefix           = local.name_prefix
  create                = var.create_api_instance
  instance_type         = var.api_instance_type
  subnet_id             = module.network.private_subnet_ids[0]
  security_group_id     = module.security_groups.api_security_group_id
  instance_profile_name = module.iam.api_instance_profile_name
}

data "aws_caller_identity" "current" {}
