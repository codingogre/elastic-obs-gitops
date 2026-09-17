output "gitops_events_data_stream" {
  value = module.foundation.gitops_events_data_stream
}

output "data_view_ids" {
  value = module.foundation.data_view_ids
}

output "gate_ids" {
  value = { for k, s in module.service : k => s.gate_id }
}

output "alerting_v2_rule_ids" {
  value = try(module.alerting_v2[0].rule_ids, {})
}

output "workflow_ids" {
  value = module.workflows.workflow_ids
}
