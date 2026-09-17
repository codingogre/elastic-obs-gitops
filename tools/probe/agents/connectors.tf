# elasticstack_kibana_action_connector (schema, provider 0.16.5):
#   connector_id       "string" optional,computed :: A UUID v1 or v4 to use instead of a randomly generated ID.
#   connector_type_id  "string" required
#   name               "string" required
#   config             "string" optional,computed :: JSON; the provider injects '__tf_provider_context'
#   secrets_wo         "string" optional,sensitive,write_only :: never persisted to state
#   secrets_wo_version "string" optional :: bump to re-send secrets_wo
#   space_id           "string" optional,computed
# Every secret below is a dummy value. Never call _execute on these connectors.

locals {
  probe_connector_ids = {
    teams      = "41707128-6b5d-4473-9f67-6615e44f92af"
    servicenow = "0ac439ee-e2c3-4336-a849-62a6247c5fc3"
    pagerduty  = "a3d4b714-f929-408c-bc4b-375d523e129a"
    webhook    = "6af186ef-574a-4f86-bb1c-5a958353bd17"
    http       = "96fe922e-fd0a-4369-85c0-1c864c4a916a"
  }

  github_headers = {
    "Accept"               = "application/vnd.github+json"
    "X-GitHub-Api-Version" = "2022-11-28"
  }
}

resource "elasticstack_kibana_action_connector" "teams" {
  space_id          = var.space_id
  connector_id      = local.probe_connector_ids.teams
  name              = "gitops-probe-tf-teams"
  connector_type_id = ".teams"

  secrets_wo = jsonencode({
    webhookUrl = "https://example.invalid/hook"
  })
  secrets_wo_version = "1"
}

resource "elasticstack_kibana_action_connector" "servicenow" {
  space_id          = var.space_id
  connector_id      = local.probe_connector_ids.servicenow
  name              = "gitops-probe-tf-servicenow"
  connector_type_id = ".servicenow"

  config = jsonencode({
    apiUrl       = "https://example.invalid"
    usesTableApi = true
  })

  secrets_wo = jsonencode({
    username = "gitops-probe-dummy-user"
    password = "gitops-probe-dummy-pass-0001"
  })
  secrets_wo_version = "1"
}

resource "elasticstack_kibana_action_connector" "pagerduty" {
  space_id          = var.space_id
  connector_id      = local.probe_connector_ids.pagerduty
  name              = "gitops-probe-tf-pagerduty"
  connector_type_id = ".pagerduty"

  secrets_wo = jsonencode({
    routingKey = "gitopsprobedummyroutingkey000001"
  })
  secrets_wo_version = "1"
}

# GitHub repository_dispatch through the classic Webhook connector.
# The token travels as a secret header (secrets.secretHeaders), so it never sits in config.
resource "elasticstack_kibana_action_connector" "webhook" {
  space_id          = var.space_id
  connector_id      = local.probe_connector_ids.webhook
  name              = "gitops-probe-tf-github-dispatch-webhook"
  connector_type_id = ".webhook"

  config = jsonencode({
    url     = "https://api.github.com/repos/codingogre/elastic-obs-gitops/dispatches"
    method  = "post"
    headers = local.github_headers
    hasAuth = false
  })

  secrets_wo = jsonencode({
    secretHeaders = {
      Authorization = "Bearer gitops-probe-dummy-token"
    }
  })
  secrets_wo_version = "1"
}

# The HTTP connector (.http) is the workflow-capable generic HTTP connector (.webhook is not).
resource "elasticstack_kibana_action_connector" "http" {
  space_id          = var.space_id
  connector_id      = local.probe_connector_ids.http
  name              = "gitops-probe-tf-github-dispatch-http"
  connector_type_id = ".http"

  config = jsonencode({
    url     = "https://api.github.com"
    headers = local.github_headers
    # hasAuth = false was rejected with HTTP 400 "authType must be null or undefined if hasAuth is
    # false", with authType omitted and with authType = null. Omitting hasAuth makes the provider fail
    # with "inconsistent result after apply", so the server defaults are stated explicitly.
    # No user or password is set; the token travels as a secret header.
    hasAuth      = true
    authType     = "webhook-authentication-basic"
    hasProxyAuth = false
  })

  secrets_wo = jsonencode({
    secretHeaders = {
      Authorization = "Bearer gitops-probe-dummy-token"
    }
  })
  secrets_wo_version = "1"
}
