locals {
  services = {
    for f in fileset("${path.module}/catalog/services", "*.yaml") :
    trimsuffix(f, ".yaml") => yamldecode(file("${path.module}/catalog/services/${f}"))
  }
}

module "service" {
  source   = "./service-observability"
  for_each = local.services

  space_id = var.space_id
  settings = var.settings
  service  = each.value
}
