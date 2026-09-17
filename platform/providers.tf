# ec reads the Elastic Cloud organization key from EC_API_KEY.
provider "ec" {}

# The dev project is shared, so the platform layer only creates the space dev works in.
provider "elasticstack" {
  alias = "dev"

  kibana {
    endpoints = [var.dev_kibana_endpoint]
    api_key   = var.dev_kibana_api_key
  }
}
