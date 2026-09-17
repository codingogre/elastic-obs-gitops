provider "elasticstack" {
  kibana {
    endpoints = [var.kibana_endpoint]
    api_key   = var.kibana_api_key
  }
}

variable "kibana_endpoint" {
  description = "Kibana endpoint of the target project."
  type        = string
  sensitive   = true
}

variable "kibana_api_key" {
  description = "API key for Kibana."
  type        = string
  sensitive   = true
}
