# SPDX-License-Identifier: AGPL-3.0-only
data "aws_ami" "amazon_linux_2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

resource "aws_instance" "orchestrator" {
  count = var.create ? 1 : 0

  ami                    = data.aws_ami.amazon_linux_2023.id
  instance_type          = var.instance_type
  subnet_id              = var.subnet_id
  vpc_security_group_ids = [var.security_group_id]
  iam_instance_profile   = var.instance_profile_name

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    # 2 required so processes in Docker can use the instance profile (S3 landing from Dagster).
    http_put_response_hop_limit = 2
  }

  root_block_device {
    volume_size = 80
    volume_type = "gp3"
    encrypted   = true
  }

  user_data_replace_on_change = true

  user_data = base64encode(templatefile("${path.module}/user_data.sh.tpl", {
    aws_region            = var.aws_region
    runtime_bundle_s3_uri = var.runtime_bundle_s3_uri
    manifest_s3_uri       = var.manifest_s3_uri
    framework_image       = var.framework_image
    ecr_registry          = var.ecr_registry
    standard_env_ssm      = var.standard_env_ssm
    master_password_ssm   = var.master_password_ssm
    db_user               = var.db_user
    db_endpoint           = var.db_endpoint
    db_name               = var.db_name
  }))

  tags = {
    Name = "${var.name_prefix}-orchestrator"
    Role = "orchestrator"
  }
}
