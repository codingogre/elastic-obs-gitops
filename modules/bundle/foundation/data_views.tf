locals {
  data_views = {
    traces        = { id = "gitops-dv-traces", title = "traces-*", name = "Traces" }
    logs          = { id = "gitops-dv-logs", title = "logs-*", name = "Logs" }
    gitops_events = { id = "gitops-dv-gitops-events", title = "gitops-events*", name = "GitOps events" }
  }
}

resource "elasticstack_kibana_data_view" "this" {
  for_each = local.data_views

  space_id = var.space_id

  data_view = {
    id              = each.value.id
    name            = each.value.name
    title           = each.value.title
    time_field_name = "@timestamp"
    allow_no_index  = true
  }
}
