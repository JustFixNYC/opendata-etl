# SPDX-License-Identifier: AGPL-3.0-only
resource "random_password" "master" {
  length  = 32
  special = false
}

resource "aws_db_subnet_group" "this" {
  name       = "${var.name_prefix}-postgres"
  subnet_ids = var.private_subnet_ids

  tags = {
    Name = "${var.name_prefix}-postgres-subnets"
  }
}

resource "aws_db_parameter_group" "this" {
  name        = "${var.name_prefix}-postgres-pg16"
  family      = "postgres16"
  description = "RDS PostgreSQL 16 parameters (PostGIS/aws_s3 enabled after CREATE EXTENSION)."

  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }

  tags = {
    Name = "${var.name_prefix}-postgres-params"
  }
}

resource "aws_db_instance" "this" {
  identifier     = "${var.name_prefix}-postgres"
  engine         = "postgres"
  engine_version = var.engine_version
  instance_class = var.instance_class

  db_name  = var.database_name
  username = var.master_username
  password = random_password.master.result

  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [var.security_group_id]
  parameter_group_name   = aws_db_parameter_group.this.name

  allocated_storage     = var.allocated_storage
  max_allocated_storage = var.max_allocated_storage
  storage_encrypted     = true
  storage_type          = "gp3"

  publicly_accessible = false
  deletion_protection = var.deletion_protection

  backup_retention_period = var.backup_retention_days
  backup_window           = "03:00-04:00"
  maintenance_window      = "sun:04:00-sun:05:00"

  enabled_cloudwatch_logs_exports = ["postgresql"]

  skip_final_snapshot       = var.skip_final_snapshot
  final_snapshot_identifier = var.skip_final_snapshot ? null : "${var.name_prefix}-postgres-final"

  tags = {
    Name = "${var.name_prefix}-postgres"
  }
}

# IAM role for RDS PostgreSQL S3 import (aws_s3.table_import_from_s3).
resource "aws_iam_role" "s3_import" {
  name = "${var.name_prefix}-rds-s3-import"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "rds.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      },
    ]
  })

  tags = {
    Name = "${var.name_prefix}-rds-s3-import"
  }
}

resource "aws_iam_role_policy" "s3_import_landing" {
  name = "${var.name_prefix}-rds-s3-import-landing"
  role = aws_iam_role.s3_import.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "LandingBucketList"
        Effect = "Allow"
        Action = [
          "s3:ListBucket",
          "s3:GetBucketLocation",
        ]
        Resource = [var.landing_bucket_arn]
      },
      {
        Sid    = "LandingObjectRead"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:GetObjectVersion",
        ]
        Resource = ["${var.landing_bucket_arn}/*"]
      },
    ]
  })
}

resource "aws_db_instance_role_association" "s3_import" {
  db_instance_identifier = aws_db_instance.this.identifier
  role_arn               = aws_iam_role.s3_import.arn
  feature_name           = "s3Import"
}

# Complements the IAM role policy (same-account S3 import).
resource "aws_s3_bucket_policy" "landing_rds_import" {
  bucket = var.landing_bucket_id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowRdsS3ImportRole"
        Effect = "Allow"
        Principal = {
          AWS = aws_iam_role.s3_import.arn
        }
        Action = [
          "s3:GetObject",
          "s3:GetObjectVersion",
          "s3:ListBucket",
          "s3:GetBucketLocation",
        ]
        Resource = [
          var.landing_bucket_arn,
          "${var.landing_bucket_arn}/*",
        ]
      },
    ]
  })
}

resource "aws_ssm_parameter" "master_password" {
  name  = "${var.ssm_prefix}/postgres/master_password"
  type  = "SecureString"
  value = random_password.master.result

  tags = {
    Name = "${var.name_prefix}-postgres-master-password"
  }
}

resource "aws_ssm_parameter" "database_url_template" {
  name = "${var.ssm_prefix}/database/url_template"
  type = "String"
  value = format(
    "postgresql://%s:REPLACE_WITH_SSM_PASSWORD@%s:5432/%s?sslmode=require",
    var.master_username,
    aws_db_instance.this.address,
    var.database_name,
  )

  description = "Template DATABASE_URL; replace password from ${var.ssm_prefix}/postgres/master_password."

  tags = {
    Name = "${var.name_prefix}-database-url-template"
  }
}

resource "aws_ssm_parameter" "s3_import_role_arn" {
  name  = "${var.ssm_prefix}/postgres/s3_import_role_arn"
  type  = "String"
  value = aws_iam_role.s3_import.arn

  tags = {
    Name = "${var.name_prefix}-rds-s3-import-role"
  }
}
