# Throwaway Phase 0 probe: one minimal object per native lane, applied to dev and then destroyed.
provider "elasticstack" {
  elasticsearch {
    endpoints = [var.elasticsearch_endpoint]
    api_key   = var.elasticsearch_api_key
  }

  kibana {
    endpoints = [var.kibana_endpoint]
    api_key   = var.kibana_api_key
  }
}
