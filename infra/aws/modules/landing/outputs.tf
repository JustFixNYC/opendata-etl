# SPDX-License-Identifier: AGPL-3.0-only
output "bucket_id" {
  value = aws_s3_bucket.landing.id
}

output "bucket_arn" {
  value = aws_s3_bucket.landing.arn
}

output "bucket_name_ssm_parameter" {
  value = aws_ssm_parameter.bucket_name.name
}
