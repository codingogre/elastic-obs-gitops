variable "space_id" {
  description = "Kibana space that holds every Kibana object in this environment."
  type        = string
}

variable "settings" {
  description = "Environment settings. The only place dev and prod differ, apart from credentials."
  type = object({
    environment                 = string
    alerting_v2_enabled         = bool
    manage_global_settings      = bool
    dashboards_write_restricted = bool
    drift_policy                = string
    gitops_events_retention     = string
    gate_soak_seconds           = number
  })

  validation {
    condition     = contains(["capture", "revert"], var.settings.drift_policy)
    error_message = "settings.drift_policy must be \"capture\" or \"revert\"."
  }
}

variable "github_repository" {
  description = "owner/name of the repository that workflows dispatch events to."
  type        = string
}

variable "secrets_version" {
  description = "Bump to re-send connector secrets after a rotation."
  type        = string
  default     = "1"
}

variable "teams_webhook_url" {
  description = "Power Automate webhook URL that posts Adaptive Cards into the platform channel."
  type        = string
  sensitive   = true
  default     = null
}

variable "sn_url" {
  description = "ServiceNow instance URL."
  type        = string
  sensitive   = true
  default     = null
}

variable "sn_user" {
  description = "ServiceNow integration user."
  type        = string
  sensitive   = true
  default     = null
}

variable "sn_password" {
  description = "ServiceNow integration user's password."
  type        = string
  sensitive   = true
  default     = null
}

variable "pd_routing_key" {
  description = "PagerDuty Events API v2 routing key."
  type        = string
  sensitive   = true
  default     = null
}

variable "github_dispatch_token" {
  description = "GitHub token used by the dispatch connector to send repository_dispatch events."
  type        = string
  sensitive   = true
  default     = null
}
