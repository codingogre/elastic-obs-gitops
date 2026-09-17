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

# Onboarding policy as code. Every rule below runs at plan time, so a catalog entry that breaks one fails the
# pull request's plan with the message shown, before anything reaches an environment.
variable "service" {
  description = "One service catalog entry (catalog/services/<name>.yaml)."
  type        = any

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]+$", var.service.name)) && length(try(var.service.name, "")) <= 30
    error_message = "Service catalog: name \"${try(var.service.name, "")}\" is not valid. Use lower-case letters, digits and hyphens, start with a letter and stay within 30 characters (for example field-service)."
  }

  validation {
    condition     = try(contains([1, 2, 3], tonumber(var.service.tier)), false)
    error_message = "Service catalog: ${try(var.service.name, "this service")} has tier \"${try(var.service.tier, "")}\". The tier must be 1, 2 or 3."
  }

  validation {
    condition     = try(tonumber(var.service.tier), 0) != 1 || can(regex("^https?://", var.service.runbook_url))
    error_message = "Service catalog: ${try(var.service.name, "this service")} is tier 1, and tier 1 services need a runbook_url (an http or https link to the runbook)."
  }

  validation {
    condition     = can(regex("^[^@[:space:]]+@[^@[:space:]]+\\.[^@[:space:]]+$", var.service.contact.email))
    error_message = "Service catalog: ${try(var.service.name, "this service")} needs a contact email (contact.email), so alerts and reviews reach the owning team."
  }

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]*$", var.service.team))
    error_message = "Service catalog: ${try(var.service.name, "this service")} needs an owning team (team, lower-case letters, digits and hyphens)."
  }

  validation {
    condition     = try(tonumber(var.service.slo.availability_target) >= 90 && tonumber(var.service.slo.availability_target) <= 99.99, false)
    error_message = "Service catalog: ${try(var.service.name, "this service")} has slo.availability_target \"${try(var.service.slo.availability_target, "")}\". It must be a percentage between 90 and 99.99."
  }

  validation {
    condition     = try(tonumber(var.service.slo.latency_target) >= 50 && tonumber(var.service.slo.latency_target) <= 99.9, false)
    error_message = "Service catalog: ${try(var.service.name, "this service")} has slo.latency_target \"${try(var.service.slo.latency_target, "")}\". It must be a percentage between 50 and 99.9."
  }

  validation {
    condition     = try(tonumber(var.service.slo.latency_threshold_ms) > 0, false)
    error_message = "Service catalog: ${try(var.service.name, "this service")} needs slo.latency_threshold_ms, a latency in milliseconds greater than 0."
  }

  validation {
    condition     = can(regex("^[1-9][0-9]*d$", var.service.slo.window))
    error_message = "Service catalog: ${try(var.service.name, "this service")} has slo.window \"${try(var.service.slo.window, "")}\". Use a rolling window in days, for example 7d or 30d."
  }

  validation {
    condition     = try(tonumber(var.service.release.max_error_ratio) > 0 && tonumber(var.service.release.max_error_ratio) <= 0.5, false)
    error_message = "Service catalog: ${try(var.service.name, "this service")} has release.max_error_ratio \"${try(var.service.release.max_error_ratio, "")}\". It is a ratio, not a percentage: greater than 0 and at most 0.5 (0.02 means 2 percent)."
  }

  validation {
    condition     = try(tonumber(var.service.release.max_p95_ms) > 0, false)
    error_message = "Service catalog: ${try(var.service.name, "this service")} needs release.max_p95_ms, the release gate's p95 latency limit in milliseconds, greater than 0."
  }
}
