# Alerting v2: one ES|QL error-spike rule per service, grouped by service and version so every episode names the
# version that is failing, and one action policy that routes every episode to the remediation workflow.

locals {
  remediation_tag = "gitops-remediation"

  rules = {
    for name, svc in var.services : name => {
      # Alert well above the release objective, so a healthy baseline never pages anyone.
      threshold = format("%.3f", try(svc.alerting.error_ratio, svc.release.max_error_ratio * 2.5))
      title     = "${upper(substr(name, 0, 1))}${substr(replace(name, "-", " "), 1, -1)}"
    }
  }
}

resource "elasticgitops_alerting_v2_rule" "error_spike" {
  for_each = local.rules

  space_id    = var.space_id
  rule_id     = "svc-${each.key}-error-spike"
  name        = "${each.value.title} error spike"
  description = "More than ${format("%g", tonumber(each.value.threshold) * 100)}% of ${each.key} requests failed over 5 minutes. One episode per version; routed to remediation."
  owner       = try(var.services[each.key].team, null)
  tags        = ["gitops", "service:${each.key}", local.remediation_tag]

  schedule = {
    every    = "1m"
    lookback = "5m"
  }

  query = {
    breach_query = templatefile("${path.module}/queries/error-spike.esql.tftpl", {
      service      = each.key
      environment  = var.settings.environment
      min_requests = 20
      threshold    = each.value.threshold
    })
  }

  grouping = {
    fields = ["service", "version"]
  }

  # Open on the first breach and close on the first clean run: one open and one close notification per episode.
  recovery_strategy = "no_breach"
  state_transition = {
    pending_count    = 0
    recovering_count = 0
  }
}

resource "elasticgitops_alerting_v2_action_policy" "remediation" {
  space_id    = var.space_id
  policy_id   = "gitops-route-remediation"
  name        = "Route error spikes to remediation"
  description = "Every episode from rules tagged ${local.remediation_tag} goes to the remediation workflow when it opens and when it closes."

  destinations = [
    { type = "workflow", id = var.remediation_workflow_id },
  ]

  matcher = {
    tags       = [local.remediation_tag]
    expression = "episode_status : \"active\" or episode_status : \"inactive\""
  }

  grouping_mode = "per_episode"
  throttle = {
    strategy = "on_status_change"
  }

  depends_on = [elasticgitops_alerting_v2_rule.error_spike]
}
