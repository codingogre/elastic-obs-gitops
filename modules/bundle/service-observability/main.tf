# Golden path for one catalog service: dashboard, SLOs, burn-rate rules and an SRE agent tool.
# IDs follow docs/CONVENTIONS.md and are identical in every environment. Alerting v2 routing and the release gate
# are added by their own modules.

locals {
  svc     = var.service
  name    = local.svc.name
  title   = "${upper(substr(local.name, 0, 1))}${substr(replace(local.name, "-", " "), 1, -1)}"
  tier    = tonumber(local.svc.tier)
  runbook = try(local.svc.runbook_url, "")

  tags      = ["gitops", "service:${local.name}"]
  slo_tags  = concat(local.tags, ["tier:${local.tier}"])
  rule_tags = concat(local.tags, ["Missing Elastic Cloud API Key"]) # added by Serverless to rules created with a project API key; see CAPABILITIES.md

  query_vars = {
    service         = local.name
    max_error_ratio = local.svc.release.max_error_ratio
    max_p95_ms      = local.svc.release.max_p95_ms
  }

  queries = {
    for f in fileset("${path.module}/queries", "*.esql") :
    trimsuffix(f, ".esql") => trimspace(templatefile("${path.module}/queries/${f}", local.query_vars))
  }

  # SLO rolling window in hours, used for the burn-rate ceiling (the rate that spends the whole budget in the long window).
  window_hours = tonumber(trimsuffix(local.svc.slo.window, "d")) * 24

  # Multi-window, multi-burn-rate thresholds by tier.
  burn_windows = local.tier == 1 ? [
    { id = "fast-burn-1h", burn_rate = 14.4, long = { value = 1, unit = "h" }, short = { value = 5, unit = "m" }, long_hours = 1, action_group = "slo.burnRate.alert" },
    { id = "slow-burn-6h", burn_rate = 6, long = { value = 6, unit = "h" }, short = { value = 30, unit = "m" }, long_hours = 6, action_group = "slo.burnRate.high" },
    ] : [
    { id = "slow-burn-6h", burn_rate = 6, long = { value = 6, unit = "h" }, short = { value = 30, unit = "m" }, long_hours = 6, action_group = "slo.burnRate.high" },
    { id = "slow-burn-24h", burn_rate = 3, long = { value = 24, unit = "h" }, short = { value = 2, unit = "h" }, long_hours = 24, action_group = "slo.burnRate.medium" },
  ]

  burn_rate_params = {
    for slo, id in { availability = elasticstack_kibana_slo.availability.slo_id, latency = elasticstack_kibana_slo.latency.slo_id } :
    slo => jsonencode({
      sloId = id
      windows = [for w in local.burn_windows : {
        id                   = w.id
        burnRateThreshold    = w.burn_rate
        maxBurnRateThreshold = local.window_hours / w.long_hours
        longWindow           = w.long
        shortWindow          = w.short
        actionGroup          = w.action_group
      }]
    })
  }

  contact_line = join(" · ", compact([
    "**Team** ${local.svc.team}",
    "**Tier** ${local.tier}",
    "**Contact** [${local.svc.contact.email}](mailto:${local.svc.contact.email})",
    local.runbook != "" ? "**Runbook** [open](${local.runbook})" : "**Runbook** none",
  ]))

  header_markdown = <<-EOT
    ### ${local.title}
    ${trimsuffix(trimspace(try(local.svc.description, "")), ".")}. _Managed by Terraform, changes come through pull requests._

    ${local.contact_line}

    **Objectives** availability ${local.svc.slo.availability_target}%, ${local.svc.slo.latency_target}% of requests under ${local.svc.slo.latency_threshold_ms} ms (rolling ${local.svc.slo.window}) · **Release gate** error ratio at most ${local.svc.release.max_error_ratio}, p95 at most ${local.svc.release.max_p95_ms} ms
  EOT

  # XY chart settings shared by the three time series panels (declared in full so plans stay clean).
  temporal_x_axis = {
    domain_json       = jsonencode({ type = "fit", rounding = false })
    grid              = true
    label_orientation = "horizontal"
    scale             = "temporal"
    ticks             = true
    title             = { value = "", visible = false }
  }
  linear_y_axis = {
    domain_json       = jsonencode({ type = "full", rounding = true })
    grid              = true
    label_orientation = "horizontal"
    scale             = "linear"
    ticks             = true
    title             = { value = "", visible = false }
  }
  # Datatable column settings Kibana fills in; declared so the provider sees no inconsistent result.
  table_row_defaults    = { alignment = "left", click_filter = false, color = { type = "auto" }, visible = true }
  table_metric_defaults = { alignment = "right", color = { type = "auto" }, visible = true }

  threshold_color = { type = "static", color = "#BD271E" }

  line_decorations = {
    line_interpolation       = "linear"
    point_visibility         = "auto"
    show_current_time_marker = false
    show_end_zones           = false
  }
}

# ---------------------------------------------------------------------------------------------------------------------
# Dashboard: svc-<svc>-golden-signals. ES|QL panels only, so nothing depends on a data view ID.
# ---------------------------------------------------------------------------------------------------------------------
resource "elasticstack_kibana_dashboard" "golden_signals" {
  space_id     = var.space_id
  dashboard_id = "svc-${local.name}-golden-signals"
  title        = "${local.title} golden signals"
  description  = "Request rate, error ratio, p95 latency, versions and deploys for ${local.name}. Generated from catalog/services/${local.name}.yaml."

  time_range = {
    from = "now-1h"
    to   = "now"
  }

  refresh_interval = {
    pause = false
    value = 30000
  }

  query = {
    language = "kql"
    text     = ""
  }

  # No access_control: write_restricted fails with API keys on 9.6 Serverless (CAPABILITIES.md).
  # No tags: dashboard tags are tag saved-object IDs, and Serverless has no tagging API or Terraform resource.

  panels = [
    {
      type = "markdown"
      id   = "about"
      grid = { x = 0, y = 0, w = 48, h = 8 }
      markdown_config = {
        by_value = {
          content  = local.header_markdown
          settings = {}
        }
      }
    },
    {
      type = "vis"
      id   = "request-rate"
      grid = { x = 0, y = 8, w = 16, h = 12 }
      vis_config = {
        by_value = {
          xy_chart_config = {
            title       = "Requests per minute"
            axis        = { x = local.temporal_x_axis, y = local.linear_y_axis }
            decorations = local.line_decorations
            fitting     = { type = "none" }
            legend      = { inside = false, position = "right", truncate_after_lines = 1, visibility = "hidden" }
            query       = { expression = "", language = "kql" }
            layers = [
              {
                type = "line"
                data_layer = {
                  data_source_json      = jsonencode({ type = "esql", query = local.queries["request-rate"] })
                  ignore_global_filters = false
                  sampling              = 1
                  x_json                = jsonencode({ column = "bucket" })
                  y = [
                    { config_json = jsonencode({ axis = "y", color = { type = "auto" }, column = "requests_per_minute", label = "Requests per minute" }) },
                  ]
                }
              },
            ]
          }
        }
      }
    },
    {
      type = "vis"
      id   = "error-ratio"
      grid = { x = 16, y = 8, w = 16, h = 12 }
      vis_config = {
        by_value = {
          xy_chart_config = {
            title       = "Error ratio (release gate max ${local.svc.release.max_error_ratio})"
            axis        = { x = local.temporal_x_axis, y = local.linear_y_axis }
            decorations = local.line_decorations
            fitting     = { type = "none" }
            legend      = { inside = false, position = "bottom", truncate_after_lines = 1, visibility = "visible" }
            query       = { expression = "", language = "kql" }
            layers = [
              {
                type = "line"
                data_layer = {
                  data_source_json      = jsonencode({ type = "esql", query = local.queries["error-ratio"] })
                  ignore_global_filters = false
                  sampling              = 1
                  x_json                = jsonencode({ column = "bucket" })
                  y = [
                    { config_json = jsonencode({ axis = "y", color = { type = "auto" }, column = "error_ratio", label = "Error ratio" }) },
                    { config_json = jsonencode({ axis = "y", color = local.threshold_color, column = "release_max_error_ratio", label = "Release gate max" }) },
                  ]
                }
              },
            ]
          }
        }
      }
    },
    {
      type = "vis"
      id   = "p95-latency"
      grid = { x = 32, y = 8, w = 16, h = 12 }
      vis_config = {
        by_value = {
          xy_chart_config = {
            title       = "p95 latency ms (release gate max ${local.svc.release.max_p95_ms} ms)"
            axis        = { x = local.temporal_x_axis, y = local.linear_y_axis }
            decorations = local.line_decorations
            fitting     = { type = "none" }
            legend      = { inside = false, position = "bottom", truncate_after_lines = 1, visibility = "visible" }
            query       = { expression = "", language = "kql" }
            layers = [
              {
                type = "line"
                data_layer = {
                  data_source_json      = jsonencode({ type = "esql", query = local.queries["p95-latency"] })
                  ignore_global_filters = false
                  sampling              = 1
                  x_json                = jsonencode({ column = "bucket" })
                  y = [
                    { config_json = jsonencode({ axis = "y", color = { type = "auto" }, column = "p95_ms", label = "p95 ms" }) },
                    { config_json = jsonencode({ axis = "y", color = local.threshold_color, column = "release_max_p95_ms", label = "Release gate max" }) },
                  ]
                }
              },
            ]
          }
        }
      }
    },
    {
      type = "vis"
      id   = "by-version"
      grid = { x = 0, y = 20, w = 20, h = 10 }
      vis_config = {
        by_value = {
          datatable_config = {
            esql = {
              title                 = "Error ratio and p95 by version"
              data_source_json      = jsonencode({ type = "esql", query = local.queries["by-version"] })
              ignore_global_filters = false
              sampling              = 1
              rows = [
                { config_json = jsonencode(merge(local.table_row_defaults, { column = "service.version", label = "Version" })) },
              ]
              metrics = [
                { config_json = jsonencode(merge(local.table_metric_defaults, { column = "requests", label = "Requests" })) },
                { config_json = jsonencode(merge(local.table_metric_defaults, { column = "errors", label = "Errors" })) },
                { config_json = jsonencode(merge(local.table_metric_defaults, { column = "error_ratio", label = "Error ratio" })) },
                { config_json = jsonencode(merge(local.table_metric_defaults, { column = "p95_ms", label = "p95 ms" })) },
              ]
              styling = {
                density = { mode = "compact" }
              }
            }
          }
        }
      }
    },
    {
      type = "vis"
      id   = "deploys"
      grid = { x = 20, y = 20, w = 28, h = 10 }
      vis_config = {
        by_value = {
          datatable_config = {
            esql = {
              title                 = "Deploys and gate verdicts (last 24 hours)"
              data_source_json      = jsonencode({ type = "esql", query = local.queries["deploys"] })
              ignore_global_filters = false
              sampling              = 1
              time_range            = { from = "now-24h", to = "now" }
              rows = [
                { config_json = jsonencode(merge(local.table_row_defaults, { column = "@timestamp", label = "Time", width = 200 })) },
                { config_json = jsonencode(merge(local.table_row_defaults, { column = "event.action", label = "Event" })) },
                { config_json = jsonencode(merge(local.table_row_defaults, { column = "gitops.service_version", label = "Version" })) },
                { config_json = jsonencode(merge(local.table_row_defaults, { column = "gitops.env", label = "Environment" })) },
                { config_json = jsonencode(merge(local.table_row_defaults, { column = "gitops.verdict", label = "Gate verdict" })) },
                { config_json = jsonencode(merge(local.table_row_defaults, { column = "event.outcome", label = "Outcome" })) },
              ]
              metrics = [
                { config_json = jsonencode(merge(local.table_metric_defaults, { column = "gitops.duration_s", label = "Duration s" })) },
              ]
              styling = {
                density = { mode = "compact" }
              }
            }
          }
        }
      }
    },
  ]
}

# ---------------------------------------------------------------------------------------------------------------------
# SLOs: APM indicators over the OTel-native transaction metrics that managed OTLP produces.
# ---------------------------------------------------------------------------------------------------------------------
resource "elasticstack_kibana_slo" "availability" {
  space_id         = var.space_id
  slo_id           = "svc-${local.name}-availability"
  name             = "${local.title} availability"
  description      = "Share of ${local.name} requests that succeed. Target from catalog/services/${local.name}.yaml."
  budgeting_method = "occurrences"
  group_by         = ["*"]
  tags             = local.slo_tags

  apm_availability_indicator {
    index            = "metrics-*.otel-*"
    service          = local.name
    environment      = var.settings.environment
    transaction_type = "*"
    transaction_name = "*"
  }

  objective {
    target = local.svc.slo.availability_target / 100
  }

  time_window {
    duration = local.svc.slo.window
    type     = "rolling"
  }
}

resource "elasticstack_kibana_slo" "latency" {
  space_id         = var.space_id
  slo_id           = "svc-${local.name}-latency"
  name             = "${local.title} latency"
  description      = "Share of ${local.name} requests faster than ${local.svc.slo.latency_threshold_ms} ms. Target from catalog/services/${local.name}.yaml."
  budgeting_method = "occurrences"
  group_by         = ["*"]
  tags             = local.slo_tags

  apm_latency_indicator {
    index            = "metrics-*.otel-*"
    service          = local.name
    environment      = var.settings.environment
    transaction_type = "*"
    transaction_name = "*"
    threshold        = local.svc.slo.latency_threshold_ms
  }

  objective {
    target = local.svc.slo.latency_target / 100
  }

  time_window {
    duration = local.svc.slo.window
    type     = "rolling"
  }
}

# ---------------------------------------------------------------------------------------------------------------------
# Classic SLO burn-rate rules. No actions: response routing is the Alerting v2 action policy.
# ---------------------------------------------------------------------------------------------------------------------
resource "elasticstack_kibana_alerting_rule" "availability_burn_rate" {
  space_id     = var.space_id
  rule_id      = "svc-${local.name}-availability-burn-rate"
  name         = "${local.title} availability burn rate"
  consumer     = "slo"
  rule_type_id = "slo.rules.burnRate"
  interval     = "1m"
  enabled      = true
  tags         = local.rule_tags
  params       = local.burn_rate_params.availability
}

resource "elasticstack_kibana_alerting_rule" "latency_burn_rate" {
  space_id     = var.space_id
  rule_id      = "svc-${local.name}-latency-burn-rate"
  name         = "${local.title} latency burn rate"
  consumer     = "slo"
  rule_type_id = "slo.rules.burnRate"
  interval     = "1m"
  enabled      = true
  tags         = local.rule_tags
  params       = local.burn_rate_params.latency
}

# ---------------------------------------------------------------------------------------------------------------------
# Agent Builder ES|QL tool for the SRE agent: gitops-svc-<svc>-health.
# ---------------------------------------------------------------------------------------------------------------------
resource "elasticstack_kibana_agentbuilder_tool" "health" {
  space_id    = var.space_id
  tool_id     = "gitops-svc-${local.name}-health"
  type        = "esql"
  description = "Current health of the ${local.name} service (team ${local.svc.team}, tier ${local.tier}). Returns one row per service.version seen in the last 30 minutes: requests, errors, error_ratio (errors divided by requests) and p95_ms (95th percentile server latency in milliseconds). A version is unhealthy when error_ratio is above the release gate maximum of ${local.svc.release.max_error_ratio} or p95_ms is above ${local.svc.release.max_p95_ms}. Use it to check whether a release is hurting the service and which version is responsible. No parameters."
  tags        = local.tags

  configuration = jsonencode({
    query  = local.queries["health-tool"]
    params = {}
  })
}
