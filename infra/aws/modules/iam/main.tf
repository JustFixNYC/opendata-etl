# SPDX-License-Identifier: AGPL-3.0-only
data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

# --- Orchestrator (EC2 reference path) ---
resource "aws_iam_role" "orchestrator" {
  name = "${var.name_prefix}-orchestrator"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      },
    ]
  })
}

resource "aws_iam_role_policy_attachment" "orchestrator_ssm" {
  role       = aws_iam_role.orchestrator.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy" "orchestrator" {
  name = "${var.name_prefix}-orchestrator-inline"
  role = aws_iam_role.orchestrator.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "LandingS3"
        Effect = "Allow"
        Action = [
          "s3:ListBucket",
          "s3:GetBucketLocation",
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
        ]
        Resource = [
          var.landing_bucket_arn,
          "${var.landing_bucket_arn}/*",
        ]
      },
      {
        Sid    = "ReadDeploymentSecrets"
        Effect = "Allow"
        Action = [
          "ssm:GetParameter",
          "ssm:GetParameters",
          "ssm:GetParametersByPath",
        ]
        Resource = "arn:aws:ssm:${data.aws_region.current.id}:${data.aws_caller_identity.current.account_id}:parameter${var.ssm_prefix}/*"
      },
      {
        Sid    = "EKSJobControl"
        Effect = "Allow"
        Action = [
          "eks:DescribeCluster",
          "eks:ListClusters",
        ]
        Resource = "*"
      },
      {
        Sid    = "EKSJobsSteps2122"
        Effect = "Allow"
        Action = [
          "eks:DescribeNodegroup",
          "eks:ListNodegroups",
        ]
        Resource = "*"
      },
      {
        Sid    = "ECRPull"
        Effect = "Allow"
        Action = [
          "ecr:GetAuthorizationToken",
          "ecr:BatchCheckLayerAvailability",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage",
        ]
        Resource = "*"
      },
    ]
  })
}

resource "aws_iam_instance_profile" "orchestrator" {
  name = "${var.name_prefix}-orchestrator"
  role = aws_iam_role.orchestrator.name
}

# --- API host (optional EC2) ---
resource "aws_iam_role" "api" {
  name = "${var.name_prefix}-api"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      },
    ]
  })
}

resource "aws_iam_role_policy_attachment" "api_ssm" {
  role       = aws_iam_role.api.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy" "api" {
  name = "${var.name_prefix}-api-inline"
  role = aws_iam_role.api.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ReadApiSecrets"
        Effect = "Allow"
        Action = [
          "ssm:GetParameter",
          "ssm:GetParameters",
        ]
        Resource = "arn:aws:ssm:${data.aws_region.current.id}:${data.aws_caller_identity.current.account_id}:parameter${var.ssm_prefix}/*"
      },
    ]
  })
}

resource "aws_iam_instance_profile" "api" {
  name = "${var.name_prefix}-api"
  role = aws_iam_role.api.name
}

# Placeholder parameters — operators set values out-of-band (never commit secrets).
resource "aws_ssm_parameter" "definitions_manifest" {
  name  = "${var.ssm_prefix}/definitions/manifest_s3_uri"
  type  = "String"
  value = "s3://REPLACE-CONFIG-BUCKET/definitions.yml"

  lifecycle {
    ignore_changes = [value]
  }

  description = "URI to definitions.yml for the orchestrator (update after deploy)."

  tags = {
    Name = "${var.name_prefix}-definitions-manifest-uri"
  }
}

resource "aws_ssm_parameter" "scaled_env" {
  name = "${var.ssm_prefix}/runtime/scaled_env"
  type = "String"
  value = join("\n", [
    "OPENDATA_LANDING_BACKEND=s3",
    "OPENDATA_LOAD_BACKEND=copy_local",
    "OPENDATA_DERIVED_EXECUTOR=eks",
    "OPENDATA_EXTRACT_EXECUTOR=eks",
    "S3_BUCKET=${var.landing_bucket_id}",
  ])

  description = "Reference env flags for scaled profile (Steps 20–22 extend load/executors)."

  tags = {
    Name = "${var.name_prefix}-scaled-env-reference"
  }
}
