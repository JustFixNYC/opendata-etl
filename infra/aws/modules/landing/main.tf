# SPDX-License-Identifier: AGPL-3.0-only
resource "aws_s3_bucket" "landing" {
  bucket        = var.bucket_name
  force_destroy = var.force_destroy

  tags = {
    Name = "${var.name_prefix}-landing"
    Role = "landing-zone"
  }
}

resource "aws_s3_bucket_versioning" "landing" {
  bucket = aws_s3_bucket.landing.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "landing" {
  bucket = aws_s3_bucket.landing.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "landing" {
  bucket = aws_s3_bucket.landing.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "landing" {
  count  = var.lifecycle_expire_days > 0 ? 1 : 0
  bucket = aws_s3_bucket.landing.id

  rule {
    id     = "expire-extract"
    status = "Enabled"

    filter {
      prefix = "extract/"
    }

    expiration {
      days = var.lifecycle_expire_days
    }

    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }

  rule {
    id     = "expire-derived"
    status = "Enabled"

    filter {
      prefix = "derived/"
    }

    expiration {
      days = var.lifecycle_expire_days
    }
  }

  rule {
    id     = "abort-incomplete-multipart"
    status = "Enabled"

    filter {}

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

resource "aws_ssm_parameter" "bucket_name" {
  name  = "${var.ssm_prefix}/landing/bucket"
  type  = "String"
  value = aws_s3_bucket.landing.id

  tags = {
    Name = "${var.name_prefix}-landing-bucket"
  }
}
