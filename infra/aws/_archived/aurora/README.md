# Archived Aurora module (Step 19)

This directory preserves the Step 19 **Aurora PostgreSQL** cluster module replaced in **Step 19b** by `infra/aws/modules/postgres_rds/` (single RDS instance for lower POC cost; same `aws_s3` import path).

To restore Aurora:

1. Copy `*.tf` back to `infra/aws/modules/aurora/`.
2. Swap `module "postgres_rds"` for `module "aurora"` in `infra/aws/main.tf` and restore Aurora-specific variables/outputs.

The parallel POC uses **RDS PostgreSQL 16** (`db.t4g.medium` default). See the master plan Step 19b handoff.
