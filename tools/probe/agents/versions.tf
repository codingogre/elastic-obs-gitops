# Phase 0 throwaway probe: native elasticstack lanes for connectors, workflows and Agent Builder.
# Applied to dev (space from var.space_id), then destroyed.
terraform {
  required_version = ">= 1.11.0"

  required_providers {
    elasticstack = {
      source  = "elastic/elasticstack"
      version = "0.16.5"
    }
  }
}
