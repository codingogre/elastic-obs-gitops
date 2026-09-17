variable "space_id" {
  type = string
}

variable "settings" {
  type = object({
    environment                 = string
    alerting_v2_enabled         = bool
    manage_global_settings      = bool
    dashboards_write_restricted = bool
    drift_policy                = string
    gitops_events_retention     = string
    gate_soak_seconds           = number
  })
}
