output "gitops_events_data_stream" {
  value = "gitops-events"
}

output "data_view_ids" {
  value = { for k, v in elasticstack_kibana_data_view.this : k => v.data_view.id }
}
