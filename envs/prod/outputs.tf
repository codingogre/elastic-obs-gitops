output "gitops_events_data_stream" {
  value = module.bundle.gitops_events_data_stream
}

output "data_view_ids" {
  value = module.bundle.data_view_ids
}

output "gate_ids" {
  value = module.bundle.gate_ids
}

output "alerting_v2_rule_ids" {
  value = module.bundle.alerting_v2_rule_ids
}

output "workflow_ids" {
  value = module.bundle.workflow_ids
}
