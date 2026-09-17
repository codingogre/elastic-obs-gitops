variable "space_id" {
  type = string
}

variable "settings" {
  type = object({
    environment             = string
    alerting_v2_enabled     = bool
    manage_global_settings  = bool
    operator_role           = bool
    drift_policy            = string
    gitops_events_retention = string
    gate_soak_seconds       = number
  })
}

variable "connector_ids" {
  type = map(string)
}

variable "github_repository" {
  type = string
}

variable "secrets_version" {
  type = string
}

variable "teams_webhook_url" {
  type      = string
  sensitive = true
  default   = null
}

variable "sn_url" {
  type      = string
  sensitive = true
  default   = null
}

variable "sn_user" {
  type      = string
  sensitive = true
  default   = null
}

variable "sn_password" {
  type      = string
  sensitive = true
  default   = null
}

variable "pd_routing_key" {
  type      = string
  sensitive = true
  default   = null
}

variable "github_dispatch_token" {
  type      = string
  sensitive = true
  default   = null
}
