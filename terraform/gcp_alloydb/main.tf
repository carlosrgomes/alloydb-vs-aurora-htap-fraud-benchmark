terraform {
  required_version = ">= 1.5.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 5.30.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

data "google_project" "current" {}

resource "google_project_service" "required_apis" {
  for_each = toset([
    "alloydb.googleapis.com",
    "compute.googleapis.com",
    "servicenetworking.googleapis.com",
    "aiplatform.googleapis.com",
  ])
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_compute_network" "benchmark_vpc" {
  name                    = "${var.cluster_id}-vpc"
  auto_create_subnetworks = false
  depends_on              = [google_project_service.required_apis]
}

resource "google_compute_subnetwork" "benchmark_subnet" {
  name                     = "${var.cluster_id}-subnet"
  ip_cidr_range            = "10.20.0.0/20"
  region                   = var.region
  network                  = google_compute_network.benchmark_vpc.id
  private_ip_google_access = true
}

resource "google_compute_firewall" "allow_iap_ssh" {
  name    = "${var.cluster_id}-allow-iap-ssh"
  network = google_compute_network.benchmark_vpc.id

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }

  source_ranges = ["35.235.240.0/20"]
  target_tags   = ["benchmark-loadgen"]
}

resource "google_compute_router" "nat_router" {
  name    = "${var.cluster_id}-router"
  region  = var.region
  network = google_compute_network.benchmark_vpc.id
}

resource "google_compute_router_nat" "cloud_nat" {
  name                               = "${var.cluster_id}-nat"
  router                             = google_compute_router.nat_router.name
  region                             = var.region
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"
}

resource "google_compute_global_address" "psa_range" {
  name          = "${var.cluster_id}-psa-range"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 16
  network       = google_compute_network.benchmark_vpc.id
}

resource "google_service_networking_connection" "private_vpc_connection" {
  network                 = google_compute_network.benchmark_vpc.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.psa_range.name]
  deletion_policy         = "ABANDON"
  depends_on              = [google_project_service.required_apis]
}

resource "google_alloydb_cluster" "fraud_htap_cluster" {
  cluster_id          = var.cluster_id
  location            = var.region
  database_version    = "POSTGRES_16"
  deletion_protection = false

  network_config {
    network = google_compute_network.benchmark_vpc.id
  }

  initial_user {
    user     = "postgres"
    password = var.db_password
  }

  depends_on = [google_service_networking_connection.private_vpc_connection]
}

resource "google_project_iam_member" "alloydb_vertex_ai_user" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:service-${data.google_project.current.number}@gcp-sa-alloydb.iam.gserviceaccount.com"

  depends_on = [google_alloydb_cluster.fraud_htap_cluster]
}

resource "google_alloydb_instance" "primary_4vcpu_32gb" {
  cluster       = google_alloydb_cluster.fraud_htap_cluster.name
  instance_id   = "${var.cluster_id}-primary"
  instance_type = "PRIMARY"

  machine_config {
    cpu_count = var.cpu_count
  }

  database_flags = {
    "google_columnar_engine.enabled"             = "on"
    "google_columnar_engine.memory_size_in_mb"   = "8192"
    "scann.enable_preview_features"              = "on"
    "google_ml_integration.enable_model_support" = "on"
    "max_connections"                            = "500"
  }

  depends_on = [google_project_iam_member.alloydb_vertex_ai_user]
}

resource "google_service_account" "loadgen_sa" {
  account_id   = "${var.cluster_id}-loadgen-sa"
  display_name = "Dedicated least-privilege Service Account for AlloyDB Benchmark Load Generator"
}

resource "google_compute_instance" "loadgen_vm" {
  name         = "${var.cluster_id}-loadgen"
  machine_type = "c3-standard-4"
  zone         = var.zone
  tags         = ["benchmark-loadgen"]

  boot_disk {
    initialize_params {
      image = "debian-cloud/debian-12"
      size  = 50
      type  = "pd-ssd"
    }
  }

  network_interface {
    subnetwork = google_compute_subnetwork.benchmark_subnet.id
  }

  metadata_startup_script = <<-EOT
    #!/bin/bash
    set -euo pipefail
    apt-get update -y
    apt-get install -y python3-venv python3-pip git postgresql-client
  EOT

  service_account {
    email = google_service_account.loadgen_sa.email
    scopes = [
      "https://www.googleapis.com/auth/logging.write",
      "https://www.googleapis.com/auth/monitoring.write",
    ]
  }
}

output "alloydb_primary_ip" {
  description = "Private IP address of the 4 vCPU / 32 GB AlloyDB Primary Instance"
  value       = google_alloydb_instance.primary_4vcpu_32gb.ip_address
}

output "loadgen_vm_internal_ip" {
  description = "Internal IP address of the co-located c3-standard-4 load generator VM"
  value       = google_compute_instance.loadgen_vm.network_interface[0].network_ip
}
