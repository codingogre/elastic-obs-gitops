locals {
  # Fixed connector UUIDs, identical in every environment (docs/CONVENTIONS.md).
  connector_ids = {
    teams           = "abd684be-bb1c-4dec-81ba-ce4e6922bad3"
    servicenow      = "846af0d6-5963-4c2d-b510-f48d525999f8"
    pagerduty       = "49d5a547-b980-426b-a5a4-f00f3ab6e473"
    github_dispatch = "e5ab5e5b-6f2b-488a-b140-a474987298bf"
  }
}

module "foundation" {
  source = "./foundation"

  space_id              = var.space_id
  settings              = var.settings
  connector_ids         = local.connector_ids
  github_repository     = var.github_repository
  secrets_version       = var.secrets_version
  teams_webhook_url     = var.teams_webhook_url
  sn_url                = var.sn_url
  sn_user               = var.sn_user
  sn_password           = var.sn_password
  pd_routing_key        = var.pd_routing_key
  github_dispatch_token = var.github_dispatch_token
}

module "workflows" {
  source = "./workflows"

  space_id      = var.space_id
  settings      = var.settings
  connector_ids = local.connector_ids
}

module "agents" {
  source = "./agents"

  space_id         = var.space_id
  settings         = var.settings
  workflow_ids     = module.workflows.workflow_ids
  service_tool_ids = [for s in module.service : s.health_tool_id]
}
