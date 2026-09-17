# Objects first built in the dev UI and captured into Git by scripts/capture.py. They keep the ID they were given
# in the UI, so promotion creates them in prod with the same ID.

locals {
  # dashboards/<slug>.json holds {"id": "<dashboard id>", "data": <Dashboards API data object>}.
  dashboards = {
    for f in fileset("${path.module}/dashboards", "*.json") :
    trimsuffix(f, ".json") => jsondecode(file("${path.module}/dashboards/${f}"))
  }

  # workflows/<workflow id>.yaml is the workflow exactly as stored in Kibana.
  workflows = toset([for f in fileset("${path.module}/workflows", "*.yaml") : trimsuffix(f, ".yaml")])
}

resource "elasticgitops_dashboard" "this" {
  for_each = local.dashboards

  space_id       = var.space_id
  dashboard_id   = each.value.id
  dashboard_json = jsonencode(each.value.data)
}

resource "elasticstack_kibana_agentbuilder_workflow" "this" {
  for_each = local.workflows

  space_id           = var.space_id
  workflow_id        = each.key
  configuration_yaml = file("${path.module}/workflows/${each.key}.yaml")
}
