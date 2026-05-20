# SPDX-License-Identifier: AGPL-3.0-only
provider "aws" {
  region = var.aws_region

  default_tags {
    tags = merge(
      {
        Project     = var.project_name
        Environment = var.environment
        ManagedBy   = "terraform"
        Component   = "opendata-etl-scaled"
      },
      var.tags,
    )
  }
}
