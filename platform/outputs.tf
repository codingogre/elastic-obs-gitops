output "prod_project_id" {
  value = ec_observability_project.prod.id
}

output "prod_endpoints" {
  description = "Kibana, Elasticsearch and managed OTLP endpoints of the prod project."
  value = {
    kibana        = ec_observability_project.prod.endpoints.kibana
    elasticsearch = ec_observability_project.prod.endpoints.elasticsearch
    ingest        = ec_observability_project.prod.endpoints.ingest
  }
}

output "dev_space_id" {
  value = elasticstack_kibana_space.gitops_dev.space_id
}
