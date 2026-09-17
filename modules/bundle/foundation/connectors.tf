# Response-tool connectors. The IDs are fixed UUIDs, identical in every environment (docs/CONVENTIONS.md),
# because workflows reference them by ID and connector_id accepts UUID v1/v4 only.
#
# Secrets travel only through the write-only `secrets_wo`, so they never reach state or plan output.
# Bump var.secrets_version to re-send them after a rotation.

locals {
  teams_enabled = nonsensitive(var.teams_webhook_url != null && var.teams_webhook_url != "")

  github_headers = {
    "Accept"               = "application/vnd.github+json"
    "X-GitHub-Api-Version" = "2022-11-28"
  }
}

# Microsoft Teams: posts {"text": <message>} to a Power Automate "Teams webhook request" flow.
# Created only when a webhook URL is configured for the environment.
resource "elasticstack_kibana_action_connector" "teams" {
  count = local.teams_enabled ? 1 : 0

  space_id          = var.space_id
  connector_id      = var.connector_ids.teams
  name              = "gitops-teams"
  connector_type_id = ".teams"

  secrets_wo = jsonencode({
    webhookUrl = var.teams_webhook_url
  })
  secrets_wo_version = var.secrets_version
}

# ServiceNow ITSM in Table API mode: writes /api/now/v2/table/incident directly, no Store app needed.
# Unused config keys (isOAuth, clientId, jwtKeyId, userIdentifierValue) are omitted; Kibana fills them in.
resource "elasticstack_kibana_action_connector" "servicenow" {
  space_id          = var.space_id
  connector_id      = var.connector_ids.servicenow
  name              = "gitops-servicenow"
  connector_type_id = ".servicenow"

  config = jsonencode({
    apiUrl       = nonsensitive(var.sn_url)
    usesTableApi = true
  })

  secrets_wo = jsonencode({
    username = var.sn_user
    password = var.sn_password
  })
  secrets_wo_version = var.secrets_version

  lifecycle {
    precondition {
      condition     = var.sn_url != null && var.sn_user != null && var.sn_password != null
      error_message = "The ServiceNow connector needs sn_url, sn_user and sn_password (TF_VAR_sn_url, TF_VAR_sn_user, TF_VAR_sn_password)."
    }
  }
}

# PagerDuty Events API v2.
resource "elasticstack_kibana_action_connector" "pagerduty" {
  space_id          = var.space_id
  connector_id      = var.connector_ids.pagerduty
  name              = "gitops-pagerduty"
  connector_type_id = ".pagerduty"

  secrets_wo = jsonencode({
    routingKey = var.pd_routing_key
  })
  secrets_wo_version = var.secrets_version

  lifecycle {
    precondition {
      condition     = var.pd_routing_key != null
      error_message = "The PagerDuty connector needs pd_routing_key (TF_VAR_pd_routing_key)."
    }
  }
}

# GitHub repository_dispatch through the generic HTTP connector (.http), the workflow-capable one
# (.webhook is not). Workflow steps supply method, path and body; the base URL and GitHub headers live here.
resource "elasticstack_kibana_action_connector" "github_dispatch" {
  space_id          = var.space_id
  connector_id      = var.connector_ids.github_dispatch
  name              = "gitops-github-dispatch"
  connector_type_id = ".http"

  config = jsonencode({
    url     = "https://api.github.com"
    headers = local.github_headers
    # Provider 0.16.5 has no .http config handler: omitting these server defaults fails with
    # "inconsistent result after apply", and hasAuth = false is rejected by Kibana with HTTP 400.
    # No user or password is set, so no basic credentials are sent; the token is a secret header.
    hasAuth      = true
    authType     = "webhook-authentication-basic"
    hasProxyAuth = false
  })

  secrets_wo = jsonencode({
    secretHeaders = {
      Authorization = "Bearer ${var.github_dispatch_token}"
    }
  })
  secrets_wo_version = var.secrets_version

  lifecycle {
    precondition {
      condition     = var.github_dispatch_token != null
      error_message = "The GitHub dispatch connector needs github_dispatch_token (TF_VAR_github_dispatch_token)."
    }
  }
}
