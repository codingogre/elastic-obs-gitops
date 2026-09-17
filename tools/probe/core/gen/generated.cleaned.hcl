# __generated__ by Terraform
# Please review these resources and move them into your main configuration files.

# __generated__ by Terraform
resource "elasticstack_kibana_dashboard" "ui" {
  dashboard_id = "gitops-probe-tf-core-ui-dashboard"
  description  = "Stand-in for a dashboard made in the UI (Phase 0 capture probe)."
  panels = [
    {
      grid = {
        h = 8
        w = 12
        x = 0
        y = 0
      }
      id = "notes"
      markdown_config = {
        by_value = {
          content = "## Grid dispatch\nCaptured from the UI."
          settings = {
          }
        }
      }
      type = "markdown"
    },
    {
      grid = {
        h = 8
        w = 12
        x = 12
        y = 0
      }
      id   = "request-count"
      type = "vis"
      vis_config = {
        by_value = {
          metric_chart_config = {
            data_source_json = jsonencode({
              query = "FROM traces-* | WHERE service.name == \"grid-dispatch\" AND kind == \"Server\" | STATS requests = COUNT(*)"
              type  = "esql"
            })
            ignore_global_filters = false
            metrics = [
              {
                config_json = jsonencode({
                  color = {
                    type = "auto"
                  }
                  column = "requests"
                  type   = "primary"
                })
              },
            ]
            sampling = 1
            title    = "Requests"
          }
        }
      }
    },
    {
      grid = {
        h = 8
        w = 24
        x = 24
        y = 0
      }
      id   = "requests-over-time"
      type = "vis"
      vis_config = {
        by_value = {
          xy_chart_config = {
            axis = {
              x = {
                domain_json = jsonencode({
                  rounding = false
                  type     = "fit"
                })
                grid              = true
                label_orientation = "horizontal"
                scale             = "temporal"
                ticks             = true
                title = {
                  value   = ""
                  visible = true
                }
              }
              y = {
                domain_json = jsonencode({
                  rounding = true
                  type     = "full"
                })
                grid              = true
                label_orientation = "horizontal"
                scale             = "linear"
                ticks             = true
                title = {
                  value   = ""
                  visible = true
                }
              }
            }
            decorations = {
              line_interpolation       = "linear"
              point_visibility         = "auto"
              show_current_time_marker = false
              show_end_zones           = false
            }
            # Required by the schema; absent from the API response for this chart.
            fitting = {
              type = "none"
            }
            layers = [
              {
                data_layer = {
                  data_source_json = jsonencode({
                    query = "FROM traces-* | WHERE @timestamp <= ?_tend AND @timestamp > ?_tstart AND service.name == \"grid-dispatch\" AND kind == \"Server\" | STATS requests = COUNT(*) BY bucket = BUCKET(@timestamp, 75, ?_tstart, ?_tend)"
                    type  = "esql"
                  })
                  ignore_global_filters = false
                  sampling              = 1
                  x_json = jsonencode({
                    column = "bucket"
                  })
                  y = [
                    {
                      config_json = jsonencode({
                        axis = "y"
                        color = {
                          type = "auto"
                        }
                        column = "requests"
                      })
                    },
                  ]
                }
                type = "line"
              },
            ]
            legend = {
              inside               = false
              position             = "right"
              truncate_after_lines = 1
              visibility           = "hidden"
            }
            query = {
              expression = ""
              language   = "kql"
            }
            title = "Requests over time"
          }
        }
      }
    },
  ]
  # Required by the schema but absent from the API response of a dashboard saved without them.
  query = {
    language = "kql"
    text     = ""
  }
  refresh_interval = {
    pause = true
    value = 60000
  }
  space_id = "gitops-dev"
  time_range = {
    from = "now-1h"
    to   = "now"
  }
  title = "gitops-probe-tf-core UI stand-in dashboard"
}
