# GitOps Control Tower: the pipeline's own delivery metrics, read from the gitops-events data stream (docs/PLAN.md P8).
# Each project's stream holds the events of the pipeline that deploys to it, so the dashboard reads the same in every
# environment. ES|QL panels only, so nothing depends on a data view ID.

locals {
  control_tower_queries = {
    for f in fileset("${path.module}/queries/control-tower", "*.esql") :
    trimsuffix(f, ".esql") => trimspace(file("${path.module}/queries/control-tower/${f}"))
  }

  # XY chart settings shared by the bar charts (declared in full so plans stay clean).
  ct_temporal_x_axis = {
    domain_json       = jsonencode({ type = "fit", rounding = false })
    grid              = true
    label_orientation = "horizontal"
    scale             = "temporal"
    ticks             = true
    title             = { value = "", visible = false }
  }
  ct_linear_y_axis = {
    domain_json       = jsonencode({ type = "full", rounding = true })
    grid              = true
    label_orientation = "horizontal"
    scale             = "linear"
    ticks             = true
    title             = { value = "", visible = false }
  }
  ct_bar_decorations = {
    show_current_time_marker = false
    show_end_zones           = false
  }
  # Datatable column settings Kibana fills in; declared so the provider sees no inconsistent result.
  ct_table_row_defaults    = { alignment = "left", click_filter = false, color = { type = "auto" }, visible = true }
  ct_table_metric_defaults = { alignment = "right", color = { type = "auto" }, visible = true }

  ct_verdict_colors = {
    pass = { type = "static", color = "#54B399" }
    warn = { type = "static", color = "#D6BF57" }
    fail = { type = "static", color = "#BD271E" }
  }

  control_tower_markdown = <<-EOT
    ### GitOps Control Tower
    How the observability-as-code pipeline performs, from the `gitops-events` stream it writes on every apply, promotion, release, gate and drift check. _Managed by Terraform, changes come through pull requests._

    **Change failure rate** releases blocked by their gate or rolled back · **Lead time** first commit to the promoted release being applied (median) · **Drift MTTR** detection to revert (mean)
  EOT
}

resource "elasticstack_kibana_dashboard" "control_tower" {
  space_id     = var.space_id
  dashboard_id = "ops-gitops-control-tower"
  title        = "GitOps Control Tower"
  description  = "Deploy frequency, change failure rate, lead time, drift MTTR, UI captures, drifted resources, gate verdicts and bundle versions, from the gitops-events data stream."

  time_range = {
    from = "now-7d"
    to   = "now"
  }

  refresh_interval = {
    pause = false
    value = 60000
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
      grid = { x = 0, y = 0, w = 48, h = 6 }
      markdown_config = {
        by_value = {
          content  = local.control_tower_markdown
          settings = {}
        }
      }
    },
    {
      type = "vis"
      id   = "change-failure-rate"
      grid = { x = 0, y = 6, w = 12, h = 8 }
      vis_config = {
        by_value = {
          metric_chart_config = {
            title                 = "Change failure rate"
            data_source_json      = jsonencode({ type = "esql", query = local.control_tower_queries["change-failure-rate"] })
            ignore_global_filters = false
            sampling              = 1
            metrics = [
              { config_json = jsonencode({ type = "primary", column = "change_failure_pct", color = { type = "auto" }, label = "% of releases" }) },
            ]
          }
        }
      }
    },
    {
      type = "vis"
      id   = "lead-time"
      grid = { x = 12, y = 6, w = 12, h = 8 }
      vis_config = {
        by_value = {
          metric_chart_config = {
            title                 = "Lead time"
            data_source_json      = jsonencode({ type = "esql", query = local.control_tower_queries["lead-time"] })
            ignore_global_filters = false
            sampling              = 1
            metrics = [
              { config_json = jsonencode({ type = "primary", column = "lead_time_minutes", color = { type = "auto" }, label = "Minutes, first commit to promotion" }) },
            ]
          }
        }
      }
    },
    {
      type = "vis"
      id   = "drift-mttr"
      grid = { x = 24, y = 6, w = 12, h = 8 }
      vis_config = {
        by_value = {
          metric_chart_config = {
            title                 = "Drift MTTR"
            data_source_json      = jsonencode({ type = "esql", query = local.control_tower_queries["drift-mttr"] })
            ignore_global_filters = false
            sampling              = 1
            metrics = [
              { config_json = jsonencode({ type = "primary", column = "mttr_minutes", color = { type = "auto" }, label = "Minutes, detection to revert" }) },
            ]
          }
        }
      }
    },
    {
      type = "vis"
      id   = "bundle-version"
      grid = { x = 36, y = 6, w = 12, h = 8 }
      vis_config = {
        by_value = {
          datatable_config = {
            esql = {
              title                 = "Current bundle version"
              data_source_json      = jsonencode({ type = "esql", query = local.control_tower_queries["bundle-version"] })
              ignore_global_filters = false
              sampling              = 1
              time_range            = { from = "now-30d", to = "now" }
              rows = [
                { config_json = jsonencode(merge(local.ct_table_row_defaults, { column = "gitops.env", label = "Environment" })) },
                { config_json = jsonencode(merge(local.ct_table_row_defaults, { column = "bundle_version", label = "Bundle" })) },
                { config_json = jsonencode(merge(local.ct_table_row_defaults, { column = "deployed_at", label = "Deployed" })) },
              ]
              metrics = [
                { config_json = jsonencode(merge(local.ct_table_metric_defaults, { column = "hours_ago", label = "Hours ago" })) },
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
      id   = "deploy-frequency"
      grid = { x = 0, y = 14, w = 24, h = 12 }
      vis_config = {
        by_value = {
          xy_chart_config = {
            title       = "Deploy frequency (per day)"
            axis        = { x = local.ct_temporal_x_axis, y = local.ct_linear_y_axis }
            decorations = local.ct_bar_decorations
            fitting     = { type = "none" }
            legend      = { inside = false, position = "bottom", truncate_after_lines = 1, visibility = "visible" }
            query       = { expression = "", language = "kql" }
            layers = [
              {
                type = "bar_stacked"
                data_layer = {
                  data_source_json      = jsonencode({ type = "esql", query = local.control_tower_queries["deploy-frequency"] })
                  ignore_global_filters = false
                  sampling              = 1
                  x_json                = jsonencode({ column = "day" })
                  y = [
                    { config_json = jsonencode({ axis = "y", color = { type = "auto" }, column = "applies", label = "Applies" }) },
                    { config_json = jsonencode({ axis = "y", color = { type = "auto" }, column = "promotions", label = "Promotions" }) },
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
      id   = "gate-verdicts"
      grid = { x = 24, y = 14, w = 24, h = 12 }
      vis_config = {
        by_value = {
          xy_chart_config = {
            title       = "Release gate verdicts"
            axis        = { x = local.ct_temporal_x_axis, y = local.ct_linear_y_axis }
            decorations = local.ct_bar_decorations
            fitting     = { type = "none" }
            legend      = { inside = false, position = "bottom", truncate_after_lines = 1, visibility = "visible" }
            query       = { expression = "", language = "kql" }
            layers = [
              {
                type = "bar_stacked"
                data_layer = {
                  data_source_json      = jsonencode({ type = "esql", query = local.control_tower_queries["gate-verdicts"] })
                  ignore_global_filters = false
                  sampling              = 1
                  x_json                = jsonencode({ column = "bucket" })
                  y = [
                    { config_json = jsonencode({ axis = "y", color = local.ct_verdict_colors.pass, column = "passed", label = "Pass" }) },
                    { config_json = jsonencode({ axis = "y", color = local.ct_verdict_colors.warn, column = "warned", label = "Warn" }) },
                    { config_json = jsonencode({ axis = "y", color = local.ct_verdict_colors.fail, column = "failed", label = "Fail" }) },
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
      id   = "ui-captures"
      grid = { x = 0, y = 26, w = 16, h = 12 }
      vis_config = {
        by_value = {
          xy_chart_config = {
            title       = "UI captures per week"
            axis        = { x = local.ct_temporal_x_axis, y = local.ct_linear_y_axis }
            decorations = local.ct_bar_decorations
            fitting     = { type = "none" }
            legend      = { inside = false, position = "right", truncate_after_lines = 1, visibility = "hidden" }
            query       = { expression = "", language = "kql" }
            layers = [
              {
                type = "bar"
                data_layer = {
                  data_source_json      = jsonencode({ type = "esql", query = local.control_tower_queries["ui-captures"] })
                  ignore_global_filters = false
                  sampling              = 1
                  x_json                = jsonencode({ column = "week" })
                  y = [
                    { config_json = jsonencode({ axis = "y", color = { type = "auto" }, column = "captures", label = "Captures" }) },
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
      id   = "top-drifted"
      grid = { x = 16, y = 26, w = 32, h = 12 }
      vis_config = {
        by_value = {
          datatable_config = {
            esql = {
              title                 = "Top drifted resources"
              data_source_json      = jsonencode({ type = "esql", query = local.control_tower_queries["top-drifted"] })
              ignore_global_filters = false
              sampling              = 1
              rows = [
                { config_json = jsonencode(merge(local.ct_table_row_defaults, { column = "gitops.resource_address", label = "Resource" })) },
                { config_json = jsonencode(merge(local.ct_table_row_defaults, { column = "last_detected", label = "Last detected", width = 200 })) },
              ]
              metrics = [
                { config_json = jsonencode(merge(local.ct_table_metric_defaults, { column = "detections", label = "Detections" })) },
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
