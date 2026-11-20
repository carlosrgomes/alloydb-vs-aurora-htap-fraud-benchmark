terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.50.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

data "aws_availability_zones" "available" {
  state = "available"
}

resource "aws_vpc" "benchmark_vpc" {
  cidr_block           = "10.30.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    Name = "${var.cluster_identifier}-vpc"
  }
}

resource "aws_internet_gateway" "benchmark_igw" {
  vpc_id = aws_vpc.benchmark_vpc.id

  tags = {
    Name = "${var.cluster_identifier}-igw"
  }
}

resource "aws_subnet" "subnet_a" {
  vpc_id                  = aws_vpc.benchmark_vpc.id
  cidr_block              = "10.30.1.0/24"
  availability_zone       = data.aws_availability_zones.available.names[0]
  map_public_ip_on_launch = true
}

resource "aws_subnet" "subnet_b" {
  vpc_id            = aws_vpc.benchmark_vpc.id
  cidr_block        = "10.30.2.0/24"
  availability_zone = data.aws_availability_zones.available.names[1]
}

resource "aws_route_table" "public_rt" {
  vpc_id = aws_vpc.benchmark_vpc.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.benchmark_igw.id
  }
}

resource "aws_route_table_association" "subnet_a_public" {
  subnet_id      = aws_subnet.subnet_a.id
  route_table_id = aws_route_table.public_rt.id
}

resource "aws_db_subnet_group" "aurora_subnets" {
  name       = "${var.cluster_identifier}-subnets"
  subnet_ids = [aws_subnet.subnet_a.id, aws_subnet.subnet_b.id]
}

resource "aws_security_group" "aurora_sg" {
  name   = "${var.cluster_identifier}-sg"
  vpc_id = aws_vpc.benchmark_vpc.id

  ingress {
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = [aws_vpc.benchmark_vpc.cidr_block]
  }

  egress {
    description = "Allow PostgreSQL egress only within the benchmark VPC"
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = [aws_vpc.benchmark_vpc.cidr_block]
  }
}

resource "aws_rds_cluster_parameter_group" "aurora_pg16_tuned" {
  name        = "${var.cluster_identifier}-pg16-params"
  family      = "aurora-postgresql16"
  description = "Tuned parameters for fair 4 vCPU / 32 GiB HTAP + pgvector HNSW parity"

  parameter {
    name  = "maintenance_work_mem"
    value = "2097152"
  }

  parameter {
    name  = "max_parallel_workers_per_gather"
    value = "4"
  }

  parameter {
    name  = "random_page_cost"
    value = "1.1"
  }
}

resource "aws_rds_cluster" "aurora_io_optimized" {
  cluster_identifier              = var.cluster_identifier
  engine                          = "aurora-postgresql"
  engine_version                  = var.engine_version
  storage_type                    = "aurora-iopt1"
  database_name                   = "postgres"
  master_username                 = "postgres"
  master_password                 = var.db_password
  db_subnet_group_name            = aws_db_subnet_group.aurora_subnets.name
  vpc_security_group_ids          = [aws_security_group.aurora_sg.id]
  db_cluster_parameter_group_name = aws_rds_cluster_parameter_group.aurora_pg16_tuned.name
  skip_final_snapshot             = true
}

resource "aws_rds_cluster_instance" "writer_4vcpu_32gb" {
  identifier          = "${var.cluster_identifier}-writer"
  cluster_identifier  = aws_rds_cluster.aurora_io_optimized.id
  instance_class      = var.instance_class
  engine              = aws_rds_cluster.aurora_io_optimized.engine
  engine_version      = aws_rds_cluster.aurora_io_optimized.engine_version
  publicly_accessible = false
}

resource "aws_iam_role" "loadgen_ssm_role" {
  name = "${var.cluster_identifier}-loadgen-ssm-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "loadgen_ssm_core" {
  role       = aws_iam_role.loadgen_ssm_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "loadgen_profile" {
  name = "${var.cluster_identifier}-loadgen-profile"
  role = aws_iam_role.loadgen_ssm_role.name
}

data "aws_ami" "al2023_arm64" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-2023.*-arm64"]
  }
}

resource "aws_instance" "loadgen_ec2" {
  ami                    = data.aws_ami.al2023_arm64.id
  instance_type          = "c7g.xlarge"
  subnet_id              = aws_subnet.subnet_a.id
  vpc_security_group_ids = [aws_security_group.aurora_sg.id]
  iam_instance_profile   = aws_iam_instance_profile.loadgen_profile.name

  user_data = <<-EOT
    #!/bin/bash
    set -euo pipefail
    dnf install -y python3.11 python3.11-pip git postgresql16
  EOT

  tags = {
    Name = "${var.cluster_identifier}-loadgen"
  }
}

output "aurora_writer_endpoint" {
  description = "Writer endpoint of the 4 vCPU / 32 GiB Aurora PostgreSQL 16 I/O-Optimized cluster"
  value       = aws_rds_cluster.aurora_io_optimized.endpoint
}

output "loadgen_ec2_instance_id" {
  description = "EC2 Instance ID for SSM Session Manager / Run Command access"
  value       = aws_instance.loadgen_ec2.id
}

output "loadgen_ec2_private_ip" {
  description = "Private IP of the co-located c7g.xlarge load generator EC2 instance"
  value       = aws_instance.loadgen_ec2.private_ip
}
