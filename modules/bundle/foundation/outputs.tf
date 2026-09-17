output "gitops_events_data_stream" {
  value = "gitops-events"
}

output "data_view_ids" {
  value = { for k, v in elasticstack_kibana_data_view.this : k => v.data_view.id }
}

output "global_settings_ready" {
  description = "Depend on this before creating Alerting v2 objects."
  value       = [for s in elasticgitops_kibana_setting.alerting_v2 : s.id]
}

output "control_tower_dashboard_id" {
  value = elasticstack_kibana_dashboard.control_tower.dashboard_id
}
