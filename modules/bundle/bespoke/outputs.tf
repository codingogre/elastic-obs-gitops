output "dashboard_ids" {
  value = { for k, d in elasticgitops_dashboard.this : k => d.dashboard_id }
}
