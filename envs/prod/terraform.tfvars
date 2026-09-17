space_id          = "default"
github_repository = "codingogre/elastic-obs-gitops"

settings = {
  environment                 = "prod"
  alerting_v2_enabled         = true
  manage_global_settings      = true
  dashboards_write_restricted = true
  drift_policy                = "revert"
  gitops_events_retention     = "30d"
  gate_soak_seconds           = 300
}
