# SPDX-License-Identifier: AGPL-3.0-only
resource "random_password" "master" {
  length  = 32
  special = false
}

resource "aws_db_subnet_group" "this" {
  name       = "${var.name_prefix}-aurora"
  subnet_ids = var.private_subnet_ids

  tags = {
    Name = "${var.name_prefix}-aurora-subnets"
  }
}

resource "aws_rds_cluster_parameter_group" "this" {
  name        = "${var.name_prefix}-aurora-pg16"
  family      = "aurora-postgresql16"
  description = "Aurora PostgreSQL 16 cluster parameters (PostGIS enabled after CREATE EXTENSION)."

  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }

  tags = {
    Name = "${var.name_prefix}-aurora-params"
  }
}

resource "aws_rds_cluster" "this" {
  cluster_identifier = "${var.name_prefix}-aurora"
  engine             = "aurora-postgresql"
  engine_version     = var.engine_version
  database_name      = var.database_name
  master_username    = var.master_username
  master_password    = random_password.master.result

  db_subnet_group_name            = aws_db_subnet_group.this.name
  vpc_security_group_ids          = [var.security_group_id]
  db_cluster_parameter_group_name = aws_rds_cluster_parameter_group.this.name

  storage_encrypted   = true
  deletion_protection = var.deletion_protection

  backup_retention_period      = var.backup_retention_days
  preferred_backup_window      = "03:00-04:00"
  preferred_maintenance_window = "sun:04:00-sun:05:00"

  enabled_cloudwatch_logs_exports = ["postgresql"]

  skip_final_snapshot       = var.skip_final_snapshot
  final_snapshot_identifier = var.skip_final_snapshot ? null : "${var.name_prefix}-aurora-final"

  tags = {
    Name = "${var.name_prefix}-aurora"
  }
}

resource "aws_rds_cluster_instance" "writer" {
  identifier         = "${var.name_prefix}-aurora-writer"
  cluster_identifier = aws_rds_cluster.this.id
  instance_class     = var.instance_class
  engine             = aws_rds_cluster.this.engine
  engine_version     = aws_rds_cluster.this.engine_version

  publicly_accessible = false

  tags = {
    Name = "${var.name_prefix}-aurora-writer"
  }
}

resource "aws_ssm_parameter" "master_password" {
  name  = "${var.ssm_prefix}/aurora/master_password"
  type  = "SecureString"
  value = random_password.master.result

  tags = {
    Name = "${var.name_prefix}-aurora-master-password"
  }
}

resource "aws_ssm_parameter" "database_url_template" {
  name = "${var.ssm_prefix}/database/url_template"
  type = "String"
  value = format(
    "postgresql://%s:REPLACE_WITH_SSM_PASSWORD@%s:5432/%s?sslmode=require",
    var.master_username,
    aws_rds_cluster.this.endpoint,
    var.database_name,
  )

  description = "Template DATABASE_URL; replace password from ${var.ssm_prefix}/aurora/master_password or use IAM auth later."

  tags = {
    Name = "${var.name_prefix}-database-url-template"
  }
}
