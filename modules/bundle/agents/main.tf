# Agent Builder agents, skills and tools. See docs/CONVENTIONS.md.
#
# Schemas (elastic/elasticstack 0.16.5):
#   elasticstack_kibana_agentbuilder_tool   tool_id, type (esql|index_search|workflow|mcp), configuration (JSON), description, tags
#   elasticstack_kibana_agentbuilder_skill  skill_id, name, description, content (markdown), tool_ids
#   elasticstack_kibana_agentbuilder_agent  agent_id, name, description, instructions, tools, skill_ids, labels, avatar_*
# Agents have no model attribute (the project's default LLM connector is used) and are created private
# (access_control.access_mode = "private"), which the provider does not expose.

locals {
  labels = ["gitops"]

  # UI edits are captured into Git only where the drift policy is "capture"; elsewhere drift is reverted.
  capture_enabled = var.settings.drift_policy == "capture"

  service_param = {
    type        = "string"
    description = "Exact service.name of the service, for example grid-dispatch or turbine-telemetry."
  }

  # Shared ES|QL tools. Queries live in tools/<file>.esql. ES|QL parameters can only carry values, never index or
  # field names, so there is no custom field-exists tool: field checks use the built-in observability.get_index_info
  # (list-fields) or run the query itself with platform.core.execute_esql (unknown fields fail with Unknown column).
  esql_tools = {
    "gitops-error-ratio-by-version" = {
      file        = "error-ratio-by-version"
      description = "Error ratio and latency of one service split by service.version over the last 30 minutes, from server spans (kind == Server) in traces-*. Returns one row per version and environment: requests, errors, error_ratio (errors / requests, a fraction), p95_ms (95th percentile server latency in milliseconds), first_seen and last_seen (first and last request of that version in the window). Use it to tell whether an error spike or slowdown belongs to one version, for example a new release running next to the previous one. No rows means the service served no requests in the last 30 minutes."
      params      = { service = local.service_param }
    }
    "gitops-recent-deploys" = {
      file        = "recent-deploys"
      description = "Pipeline events for one service from the last 24 hours, newest first, from the gitops-events data stream: release_started, release_succeeded, rollback and gate_evaluated for the service, plus bundle-wide apply and promotion events (scope = bundle, observability configuration only, not application code). Columns: @timestamp, minutes_ago, event.action, event.outcome, scope, gitops.env, gitops.service_version, gitops.baseline_version (the version a release replaces), gitops.verdict and gitops.reasons (release gate result), gitops.bundle_version, gitops.run_url, message. Use it to correlate an error spike with a release or rollback. No rows means nothing was deployed in 24 hours."
      params      = { service = local.service_param }
    }
    "gitops-slo-feasibility" = {
      file        = "slo-feasibility"
      description = "Whether an availability SLO target is achievable for one service, from the last 7 days of server spans in traces-*. Availability = 100 * (1 - errors / requests). Returns one row per day (newest first): requests, errors, availability_pct, p95_ms, hours_with_data; and on every row the 7-day totals: overall_7d_availability_pct, worst_day_availability_pct, best_day_availability_pct, days_with_data, total_hours_with_data, total_requests, total_errors. Compare a target in percent (for example 99.99; an SLO objective of 0.9999 is 99.99) with overall_7d_availability_pct: a target above both the overall and the best day was never met. No rows means the service has no telemetry yet."
      params      = { service = local.service_param }
    }
    "gitops-rule-backtest" = {
      file        = "rule-backtest"
      description = "Backtests an error-ratio alert threshold for one service over the last 7 days of server spans in traces-*: splits the time into 5-minute buckets and counts the buckets whose error ratio (errors / requests) is above the threshold. Returns one row: error_ratio_threshold, buckets_with_data, hours_with_data, buckets_over_threshold, pct_buckets_over_threshold, estimated_breach_buckets_per_day (breaching 5-minute evaluations per day of data), max_bucket_error_ratio, median_bucket_error_ratio, min_bucket_requests, first_breach, last_breach. Use it to judge how noisy an alert rule would be before it ships. buckets_with_data = 0 means the service has no telemetry yet."
      params = {
        service = local.service_param
        error_ratio_threshold = {
          type        = "float"
          description = "Alert threshold as a fraction between 0 and 1, for example 0.02 for 2 percent of requests failing."
        }
      }
    }
  }

  # Built-in tools that only read. Built-ins marked readonly in the API are merely not editable; many of them write,
  # so this list is chosen by what each tool does.
  builtin_readonly = {
    esql          = "platform.core.execute_esql"
    search        = "platform.core.search"
    index_info    = "observability.get_index_info"
    services      = "observability.get_services"
    trace_metrics = "observability.get_trace_metrics"
    log_groups    = "observability.get_log_groups"
  }
}

# ---------------------------------------------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------------------------------------------

resource "elasticstack_kibana_agentbuilder_tool" "esql" {
  for_each = local.esql_tools

  space_id    = var.space_id
  tool_id     = each.key
  type        = "esql"
  description = each.value.description
  tags        = local.labels

  configuration = jsonencode({
    query  = trimspace(file("${path.module}/tools/${each.value.file}.esql"))
    params = each.value.params
  })
}

resource "elasticstack_kibana_agentbuilder_tool" "sync_to_git" {
  count = local.capture_enabled ? 1 : 0

  space_id    = var.space_id
  tool_id     = "gitops-sync-to-git-tool"
  type        = "workflow"
  description = "Puts a change made in the Kibana UI into Git: runs the Sync to Git workflow, which asks the GitOps pipeline to capture the object as Terraform code and open a pull request for review. It never changes anything in Kibana. Call it only when the user asks to sync, save, capture or commit a UI change to Git. For a dashboard pass object_type = dashboard and object_title = the dashboard title exactly as the user gave it; for other object types pass object_id. Put a short summary of what the user changed in note when they said it. The result is the workflow execution; the pull request appears in GitHub about a minute later."
  tags        = local.labels

  configuration = jsonencode({
    workflow_id         = var.workflow_ids.sync_to_git
    wait_for_completion = true
  })
}

# ---------------------------------------------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------------------------------------------

resource "elasticstack_kibana_agentbuilder_skill" "observability_review" {
  space_id    = var.space_id
  skill_id    = "gitops-observability-review"
  name        = "gitops-observability-review"
  description = "Review checklist for Terraform plans of Elastic observability assets: IDs and naming, tags, SLO realism against 7 days of data, alert noise backtests, ES|QL correctness, dashboard hygiene, retention cost and secrets exposure, ending in a VERDICT line."
  content     = file("${path.module}/skills/observability-gitops-review.md")

  # Kibana accepts at most 5 tools per skill (HTTP 400 "A skill can reference at most 5 tools").
  tool_ids = [
    elasticstack_kibana_agentbuilder_tool.esql["gitops-slo-feasibility"].tool_id,
    elasticstack_kibana_agentbuilder_tool.esql["gitops-rule-backtest"].tool_id,
    local.builtin_readonly.esql,
    local.builtin_readonly.index_info,
  ]
}

resource "elasticstack_kibana_agentbuilder_skill" "release_risk" {
  space_id    = var.space_id
  skill_id    = "gitops-release-risk-assessment"
  name        = "gitops-release-risk-assessment"
  description = "How to weigh an error spike against deploy timing and version differences, when to recommend a rollback, and how to state confidence."
  content     = file("${path.module}/skills/release-risk-assessment.md")

  tool_ids = [
    elasticstack_kibana_agentbuilder_tool.esql["gitops-error-ratio-by-version"].tool_id,
    elasticstack_kibana_agentbuilder_tool.esql["gitops-recent-deploys"].tool_id,
    local.builtin_readonly.log_groups,
  ]
}

# ---------------------------------------------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------------------------------------------

resource "elasticstack_kibana_agentbuilder_agent" "reviewer" {
  space_id      = var.space_id
  agent_id      = "gitops-reviewer"
  name          = "GitOps reviewer"
  description   = "Reviews Terraform plans for Elastic observability assets and checks SLO targets and alert thresholds against real data. Read-only; advisory."
  labels        = local.labels
  avatar_color  = "#BFDBFF"
  avatar_symbol = "GR"

  instructions = file("${path.module}/instructions/reviewer.md")
  skill_ids    = [elasticstack_kibana_agentbuilder_skill.observability_review.skill_id]

  tools = [
    elasticstack_kibana_agentbuilder_tool.esql["gitops-slo-feasibility"].tool_id,
    elasticstack_kibana_agentbuilder_tool.esql["gitops-rule-backtest"].tool_id,
    elasticstack_kibana_agentbuilder_tool.esql["gitops-error-ratio-by-version"].tool_id,
    elasticstack_kibana_agentbuilder_tool.esql["gitops-recent-deploys"].tool_id,
    # Field checks: get_index_info lists fields compactly. get_index_mapping on traces-* returns every backing index
    # mapping (about 200k tokens in a shared project), which made a review take minutes.
    local.builtin_readonly.esql,
    local.builtin_readonly.index_info,
  ]
}

resource "elasticstack_kibana_agentbuilder_agent" "platform_assistant" {
  space_id      = var.space_id
  agent_id      = "gitops-platform-assistant"
  name          = "Platform assistant"
  description   = "Helps developers in this space: explains what is managed from Git, answers questions about services and pipeline events, and puts UI changes into Git through a pull request. Never edits configuration."
  labels        = local.labels
  avatar_color  = "#D6F5E3"
  avatar_symbol = "PA"

  instructions = templatefile("${path.module}/instructions/platform-assistant.md.tftpl", {
    capture_enabled = local.capture_enabled
  })

  tools = concat(
    [for t in elasticstack_kibana_agentbuilder_tool.sync_to_git : t.tool_id],
    [
      elasticstack_kibana_agentbuilder_tool.esql["gitops-recent-deploys"].tool_id,
      local.builtin_readonly.services,
      local.builtin_readonly.search,
      local.builtin_readonly.index_info,
    ],
  )
}

resource "elasticstack_kibana_agentbuilder_agent" "sre_remediator" {
  space_id      = var.space_id
  agent_id      = "gitops-sre-remediator"
  name          = "SRE remediator"
  description   = "Triages error spikes and alert episodes for a service: weighs the errors by version against recent releases and recommends a rollback only when a version is clearly implicated. Advisory; a human approves."
  labels        = local.labels
  avatar_color  = "#FFD9C9"
  avatar_symbol = "SR"

  instructions = file("${path.module}/instructions/sre-remediator.md")
  skill_ids    = [elasticstack_kibana_agentbuilder_skill.release_risk.skill_id]

  tools = concat(
    [
      elasticstack_kibana_agentbuilder_tool.esql["gitops-error-ratio-by-version"].tool_id,
      elasticstack_kibana_agentbuilder_tool.esql["gitops-recent-deploys"].tool_id,
      local.builtin_readonly.log_groups,
      local.builtin_readonly.trace_metrics,
    ],
    var.service_tool_ids,
  )
}
