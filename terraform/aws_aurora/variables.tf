variable "aws_region" {
  description = "AWS region for the Aurora PostgreSQL 16 I/O-Optimized parity cluster"
  type        = string
  default     = "us-east-1"
}

variable "cluster_identifier" {
  description = "Identifier for the AWS Aurora PostgreSQL 16 cluster"
  type        = string
  default     = "aurora-htap-fraud-parity"
}

variable "db_password" {
  description = "Master password for the postgres user"
  type        = string
  sensitive   = true
}

variable "instance_class" {
  description = "4 vCPU / 32 GiB RAM instance class matching AlloyDB 4 vCPU / 32 GB"
  type        = string
  default     = "db.r7g.xlarge"
}

variable "engine_version" {
  description = "Aurora PostgreSQL 16 engine version (matching AlloyDB PostgreSQL 16.14 parity)"
  type        = string
  default     = "16.14"
}
