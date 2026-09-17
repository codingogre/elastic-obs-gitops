# Dev tracks main: every merge applies the bundle straight from this checkout.
module "bundle" {
  source = "../../modules/bundle"

  space_id              = var.space_id
  settings              = var.settings
  github_repository     = var.github_repository
  secrets_version       = var.secrets_version
  teams_webhook_url     = var.teams_webhook_url
  sn_url                = var.sn_url
  sn_user               = var.sn_user
  sn_password           = var.sn_password
  pd_routing_key        = var.pd_routing_key
  github_dispatch_token = var.github_dispatch_token
}
