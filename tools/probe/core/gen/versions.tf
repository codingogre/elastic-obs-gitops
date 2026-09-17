# Capture probe: local state only. A dashboard made outside Terraform is imported and its HCL generated.
terraform {
  required_version = ">= 1.11.0"

  required_providers {
    elasticstack = {
      source  = "elastic/elasticstack"
      version = "0.16.5"
    }
  }
}
