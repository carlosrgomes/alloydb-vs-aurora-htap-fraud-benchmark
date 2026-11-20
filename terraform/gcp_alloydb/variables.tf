variable "project_id" {
  description = "Google Cloud Project ID where AlloyDB and Vertex AI are provisioned"
  type        = string
}

variable "region" {
  description = "GCP region for AlloyDB cluster and co-located Compute Engine load generator"
  type        = string
  default     = "us-central1"
}

variable "zone" {
  description = "GCP zone for the co-located c3-standard-4 load generator VM"
  type        = string
  default     = "us-central1-a"
}

variable "cluster_id" {
  description = "Identifier for the AlloyDB cluster"
  type        = string
  default     = "alloydb-htap-fraud-cluster"
}

variable "db_password" {
  description = "Initial password for the postgres superuser"
  type        = string
  sensitive   = true
}

variable "cpu_count" {
  description = "vCPU count for strict 4 vCPU / 32 GB RAM parity against AWS Aurora db.r7g.xlarge"
  type        = number
  default     = 4
}
