# SPDX-License-Identifier: AGPL-3.0-only
resource "aws_security_group" "aurora" {
  name        = "${var.name_prefix}-aurora"
  description = "Aurora PostgreSQL — ingress from orchestrator, API, and EKS workers only."
  vpc_id      = var.vpc_id

  egress {
    description = "All outbound (patching, extensions)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.name_prefix}-aurora-sg"
    Role = "database"
  }
}

resource "aws_security_group" "orchestrator" {
  name        = "${var.name_prefix}-orchestrator"
  description = "Dagster orchestrator — submits EKS Jobs, runs load assets, reaches Aurora and S3."
  vpc_id      = var.vpc_id

  ingress {
    description = "Dagster UI"
    from_port   = 3000
    to_port     = 3000
    protocol    = "tcp"
    cidr_blocks = length(var.admin_cidr_blocks) > 0 ? var.admin_cidr_blocks : ["127.0.0.1/32"]
  }

  egress {
    description = "All outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.name_prefix}-orchestrator-sg"
    Role = "orchestrator"
  }
}

resource "aws_security_group" "api" {
  name        = "${var.name_prefix}-api"
  description = "Read-only FastAPI — query traffic only; no batch extract/derived."
  vpc_id      = var.vpc_id

  ingress {
    description = "HTTP"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = var.api_ingress_cidr_blocks
  }

  ingress {
    description = "HTTPS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = var.api_ingress_cidr_blocks
  }

  ingress {
    description = "Uvicorn direct (dev/smoke)"
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = var.api_ingress_cidr_blocks
  }

  egress {
    description = "All outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.name_prefix}-api-sg"
    Role = "api"
  }
}

resource "aws_security_group" "eks_workers" {
  name        = "${var.name_prefix}-eks-workers"
  description = "EKS managed nodes — extract/derived Job pods (no public ingress)."
  vpc_id      = var.vpc_id

  egress {
    description = "All outbound (S3, source APIs, image pulls)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.name_prefix}-eks-workers-sg"
    Role = "eks-workers"
  }
}

# Aurora:5432 from orchestrator, API, EKS workers
resource "aws_security_group_rule" "aurora_from_orchestrator" {
  type                     = "ingress"
  security_group_id        = aws_security_group.aurora.id
  source_security_group_id = aws_security_group.orchestrator.id
  from_port                = 5432
  to_port                  = 5432
  protocol                 = "tcp"
  description              = "Postgres from orchestrator"
}

resource "aws_security_group_rule" "aurora_from_api" {
  type                     = "ingress"
  security_group_id        = aws_security_group.aurora.id
  source_security_group_id = aws_security_group.api.id
  from_port                = 5432
  to_port                  = 5432
  protocol                 = "tcp"
  description              = "Postgres from API host"
}

resource "aws_security_group_rule" "aurora_from_eks" {
  type                     = "ingress"
  security_group_id        = aws_security_group.aurora.id
  source_security_group_id = aws_security_group.eks_workers.id
  from_port                = 5432
  to_port                  = 5432
  protocol                 = "tcp"
  description              = "Postgres from EKS workers (derived jobs needing read-only DB)"
}
