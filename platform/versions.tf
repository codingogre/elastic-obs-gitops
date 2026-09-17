terraform {
  required_version = ">= 1.11.0"

  required_providers {
    ec = {
      source  = "elastic/ec"
      version = "0.13.1"
    }
    elasticstack = {
      source  = "elastic/elasticstack"
      version = "0.16.5"
    }
  }
}
