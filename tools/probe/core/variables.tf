variable "elasticsearch_endpoint" {
  description = "Elasticsearch endpoint of the target project."
  type        = string
  sensitive   = true
}

variable "elasticsearch_api_key" {
  description = "API key for Elasticsearch."
  type        = string
  sensitive   = true
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

variable "space_id" {
  description = "Kibana space that holds every probe object."
  type        = string
}

variable "prefix" {
  description = "Name and ID prefix of every probe object."
  type        = string
  default     = "gitops-probe-tf-core"
}
