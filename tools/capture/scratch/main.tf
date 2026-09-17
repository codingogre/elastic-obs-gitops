# Read-only helper for scripts/capture.py: reads one dashboard through the elasticgitops data source, which
# returns the Dashboards API data with server defaults removed (the same normalization the resource uses).
terraform {
  required_providers {
    elasticgitops = {
      source  = "codingogre/elasticgitops"
      version = "0.1.0"
    }
  }
}

variable "kibana_endpoint" {
  type      = string
  sensitive = true
}

variable "kibana_api_key" {
  type      = string
  sensitive = true
}

variable "space_id" {
  type = string
}

variable "dashboard_id" {
  type = string
}

provider "elasticgitops" {
  kibana {
    endpoints = [var.kibana_endpoint]
    api_key   = var.kibana_api_key
  }
}

data "elasticgitops_dashboard" "captured" {
  space_id     = var.space_id
  dashboard_id = var.dashboard_id
}

output "title" {
  value = data.elasticgitops_dashboard.captured.title
}

output "dashboard_json" {
  value = data.elasticgitops_dashboard.captured.dashboard_json
}
