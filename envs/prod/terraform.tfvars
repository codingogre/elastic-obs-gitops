space_id          = "default"
github_repository = "codingogre/elastic-obs-gitops"

settings = {
  environment             = "prod"
  alerting_v2_enabled     = true
  manage_global_settings  = true
  operator_role           = true # gitops-operator role for people: read-only dashboards, editable SLOs and alerting
  drift_policy            = "revert"
  gitops_events_retention = "30d"
  gate_soak_seconds       = 300
}
