terraform {
  required_version = ">= 1.11.0"

  required_providers {
    elasticstack = {
      source  = "elastic/elasticstack"
      version = "0.16.5"
    }
  }
}
