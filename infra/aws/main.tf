# SPDX-License-Identifier: AGPL-3.0-only
# Reference Terraform for profile: scaled (Aurora + S3 landing + EKS + split services).
# See docs/deployment/aws-scaled.md for apply workflow and smoke tests.

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

  name_prefix             = local.name_prefix
  ssm_prefix              = local.ssm_prefix
  bucket_name             = "${local.name_prefix}-landing-${data.aws_caller_identity.current.account_id}"
  force_destroy           = var.landing_bucket_force_destroy
  lifecycle_expire_days   = var.landing_lifecycle_expire_days
}

module "aurora" {
  source = "./modules/aurora"

  name_prefix          = local.name_prefix
  ssm_prefix           = local.ssm_prefix
  private_subnet_ids   = module.network.private_subnet_ids
  security_group_id    = module.security_groups.aurora_security_group_id
  engine_version       = var.aurora_engine_version
  instance_class       = var.aurora_instance_class
  database_name        = var.aurora_database_name
  master_username      = var.aurora_master_username
  backup_retention_days = var.aurora_backup_retention_days
}

module "ecr" {
  source = "./modules/ecr"

  name_prefix = local.name_prefix
}

module "eks" {
  source = "./modules/eks"

  name_prefix               = local.name_prefix
  ssm_prefix                = local.ssm_prefix
  cluster_version           = var.eks_cluster_version
  private_subnet_ids        = module.network.private_subnet_ids
  public_subnet_ids         = module.network.public_subnet_ids
  worker_security_group_id  = module.security_groups.eks_workers_security_group_id
  node_instance_types       = var.eks_node_instance_types
  node_desired_size         = var.eks_node_desired_size
  node_min_size             = var.eks_node_min_size
  node_max_size             = var.eks_node_max_size
  landing_bucket_arn        = module.landing.bucket_arn
}

module "iam" {
  source = "./modules/iam"

  name_prefix        = local.name_prefix
  ssm_prefix         = local.ssm_prefix
  landing_bucket_arn = module.landing.bucket_arn
  landing_bucket_id  = module.landing.bucket_id
}

module "orchestrator" {
  source = "./modules/orchestrator"

  name_prefix             = local.name_prefix
  create                  = var.create_orchestrator_instance
  instance_type           = var.orchestrator_instance_type
  subnet_id               = module.network.private_subnet_ids[0]
  security_group_id       = module.security_groups.orchestrator_security_group_id
  instance_profile_name   = module.iam.orchestrator_instance_profile_name
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
