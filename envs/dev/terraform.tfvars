space_id          = "gitops-dev"
github_repository = "codingogre/elastic-obs-gitops"

settings = {
  environment                 = "dev"
  alerting_v2_enabled         = true
  manage_global_settings      = false # the dev project is shared; its global settings are not ours
  dashboards_write_restricted = false
  drift_policy                = "capture"
  gitops_events_retention     = "7d"
  gate_soak_seconds           = 60
}
