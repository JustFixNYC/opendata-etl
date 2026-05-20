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
    http_put_response_hop_limit = 1
  }

  root_block_device {
    volume_size = 80
    volume_type = "gp3"
    encrypted   = true
  }

  user_data = <<-EOT
    #!/bin/bash
    set -euo pipefail
    dnf install -y docker
    systemctl enable --now docker
    usermod -aG docker ssm-user || true
    mkdir -p /opt/opendata-etl
    cat >/opt/opendata-etl/README.txt <<'NOTE'
    Reference Dagster orchestrator (EC2). Install the framework image from ECR and run
    dagster-webserver + dagster-daemon per docs/deployment/aws-scaled.md.
    Alternative: run Dagster on EKS (documented in the same guide).
    NOTE
  EOT

  tags = {
    Name = "${var.name_prefix}-orchestrator"
    Role = "orchestrator"
  }
}
