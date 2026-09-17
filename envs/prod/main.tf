# Prod pins a released bundle. Only promotion pull requests change this ref.
module "bundle" {
  source = "../../modules/bundle" # replaced by the first promotion with git::https://github.com/codingogre/elastic-obs-gitops.git//modules/bundle?ref=obs-vX.Y.Z

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
