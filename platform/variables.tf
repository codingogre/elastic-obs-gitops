variable "prod_project_id" {
  description = "ID of the prod Serverless Observability project, imported into state."
  type        = string
}

variable "prod_project_name" {
  description = "Name of the prod Serverless Observability project."
  type        = string
}

variable "prod_region_id" {
  description = "Elastic Cloud region of the prod project."
  type        = string
}

variable "dev_space_id" {
  description = "Kibana space that holds every dev object this repository manages."
  type        = string
}

variable "dev_kibana_endpoint" {
  description = "Kibana endpoint of the dev project."
  type        = string
  sensitive   = true
}

variable "dev_kibana_api_key" {
  description = "API key for the dev project's Kibana."
  type        = string
  sensitive   = true
}
