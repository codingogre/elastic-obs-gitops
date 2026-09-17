# Lanes: Kibana data view, typed dashboard, SLOs, classic rules, maintenance window, role.

locals {
  # Serverless adds this tag to every classic rule created with a project API key. Declaring it avoids
  # "Provider produced inconsistent result after apply" on create and a perpetual diff afterwards.
  rule_tags = [var.prefix, "Missing Elastic Cloud API Key"]
}

resource "elasticstack_kibana_data_view" "events" {
  space_id = var.space_id

  data_view = {
    id              = local.events
    name            = local.events
    title           = "${local.events}*"
    time_field_name = "@timestamp"
  }
}

resource "elasticstack_kibana_dashboard" "probe" {
  space_id     = var.space_id
  dashboard_id = "${var.prefix}-dashboard"
  title        = "${var.prefix} dashboard"
  description  = "Phase 0 probe: typed dashboard with one ES|QL panel and one markdown panel."

  time_range = {
    from = "now-24h"
    to   = "now"
  }

  refresh_interval = {
    pause = true
    value = 60000
  }

  query = {
    language = "kql"
    text     = ""
  }

  # access_control = { access_mode = "write_restricted" } was dropped: on 9.6 Serverless the Dashboards API GET
  # never returns access_control, so the provider fails with "inconsistent result after apply" (see lanes-core.md).

  panels = [
    {
      type = "markdown"
      id   = "about"
      grid = { x = 0, y = 0, w = 24, h = 8 }
      markdown_config = {
        by_value = {
          content  = "Probe dashboard managed by Terraform. Updated in place."
          settings = {}
        }
      }
    },
    {
      type = "vis"
      id   = "events-count"
      grid = { x = 24, y = 0, w = 24, h = 8 }
      vis_config = {
        by_value = {
          metric_chart_config = {
            title = "Events"
            data_source_json = jsonencode({
              type  = "esql"
              query = trimspace(file("${path.module}/assets/events-count.esql"))
            })
            # Server-filled defaults are declared so an imported dashboard plans clean.
            ignore_global_filters = false
            sampling              = 1
            metrics = [
              { config_json = jsonencode({ type = "primary", column = "events", color = { type = "auto" } }) },
            ]
          }
        }
      }
    },
  ]
}

# SLO, custom KQL indicator over managed-OTLP traces.
resource "elasticstack_kibana_slo" "kql" {
  space_id         = var.space_id
  slo_id           = "${var.prefix}-grid-dispatch-kql"
  name             = "${var.prefix} grid-dispatch availability (KQL)"
  description      = "Phase 0 probe: share of grid-dispatch server spans without an error status."
  budgeting_method = "occurrences"
  group_by         = ["*"]
  tags             = [var.prefix]

  kql_custom_indicator {
    index           = "traces-*"
    timestamp_field = "@timestamp"
    filter          = "service.name : \"grid-dispatch\" and kind : \"Server\""
    good            = "not status.code : \"Error\""
    total           = "*"
  }

  objective {
    target = 0.95
  }

  time_window {
    duration = "30d"
    type     = "rolling"
  }
}

# SLO, APM availability indicator over the OTel-native transaction metrics.
resource "elasticstack_kibana_slo" "apm" {
  space_id         = var.space_id
  slo_id           = "${var.prefix}-grid-dispatch-apm"
  name             = "${var.prefix} grid-dispatch availability (APM)"
  description      = "Phase 0 probe: APM availability indicator on managed-OTLP data."
  budgeting_method = "occurrences"
  tags             = [var.prefix]

  apm_availability_indicator {
    index            = "metrics-*.otel-*"
    service          = "grid-dispatch"
    environment      = "dev"
    transaction_type = "*"
    transaction_name = "*"
  }

  objective {
    target = 0.99
  }

  time_window {
    duration = "30d"
    type     = "rolling"
  }
}

resource "elasticstack_kibana_agentbuilder_workflow" "probe" {
  space_id           = var.space_id
  workflow_id        = "${var.prefix}-workflow"
  configuration_yaml = file("${path.module}/assets/probe-workflow.yaml")
}

# Classic ES|QL rule. Its only action is the Workflows system action.
resource "elasticstack_kibana_alerting_rule" "esql" {
  space_id     = var.space_id
  rule_id      = "${var.prefix}-esql-errors"
  name         = "${var.prefix} ES|QL errors"
  consumer     = "stackAlerts"
  rule_type_id = ".es-query"
  interval     = "5m"
  enabled      = true
  tags         = local.rule_tags

  params = jsonencode({
    searchType          = "esqlQuery"
    esqlQuery           = { esql = trimspace(file("${path.module}/assets/errors-rule.esql")) }
    timeField           = "@timestamp"
    timeWindowSize      = 5
    timeWindowUnit      = "m"
    threshold           = [0]
    thresholdComparator = ">"
    size                = 100
    # Server-filled defaults, declared so an imported rule plans clean.
    aggType                    = "count"
    groupBy                    = "all"
    excludeHitsFromPreviousRun = true
  })

  actions {
    id = "system-connector-.workflows"
    params = jsonencode({
      subAction = "run"
      subActionParams = {
        workflowId  = elasticstack_kibana_agentbuilder_workflow.probe.workflow_id
        summaryMode = false
        alertStates = { new = true, ongoing = false, recovered = true }
      }
    })
  }
}

resource "elasticstack_kibana_alerting_rule" "burn_rate" {
  space_id     = var.space_id
  rule_id      = "${var.prefix}-slo-burn-rate"
  name         = "${var.prefix} SLO burn rate"
  consumer     = "slo"
  rule_type_id = "slo.rules.burnRate"
  interval     = "1m"
  enabled      = true
  tags         = local.rule_tags

  params = jsonencode({
    sloId = elasticstack_kibana_slo.kql.slo_id
    windows = [
      {
        id                   = "fast-burn-1h"
        burnRateThreshold    = 14.4
        maxBurnRateThreshold = 720
        longWindow           = { value = 1, unit = "h" }
        shortWindow          = { value = 5, unit = "m" }
        actionGroup          = "slo.burnRate.alert"
      },
    ]
  })
}

resource "elasticstack_kibana_maintenance_window" "weekly" {
  space_id = var.space_id
  title    = "${var.prefix} weekly change window"
  enabled  = false

  custom_schedule = {
    start    = "2026-09-20T02:00:00.000Z"
    duration = "2h"
    timezone = "UTC"
    recurring = {
      every       = "1w"
      on_week_day = ["SU"]
    }
  }

  scope = {
    alerting = {
      kql = "kibana.alert.rule.tags: \"${var.prefix}\""
    }
  }
}

resource "elasticstack_kibana_security_role" "probe" {
  name        = "${var.prefix}-role"
  description = "Phase 0 probe: read the probe events in the probe space."

  elasticsearch {
    indices {
      names      = ["${local.events}*"]
      privileges = ["read", "view_index_metadata"]
    }
  }

  kibana {
    base   = ["read"]
    spaces = [var.space_id]
  }
}
