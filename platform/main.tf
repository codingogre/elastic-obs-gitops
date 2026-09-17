# Prod is a dedicated Serverless Observability project. It was created before this module existed,
# so it is adopted with an import block rather than recreated.
import {
  to = ec_observability_project.prod
  id = var.prod_project_id
}

resource "ec_observability_project" "prod" {
  name         = var.prod_project_name
  region_id    = var.prod_region_id
  product_tier = "complete"
}

# Dev lives in a shared project: everything this repository manages there sits in one space.
resource "elasticstack_kibana_space" "gitops_dev" {
  provider = elasticstack.dev

  space_id    = var.dev_space_id
  name        = "GitOps dev"
  description = "Observability as code. Every object in this space is managed by Terraform from elastic-obs-gitops."
  initials    = "GO"
  color       = "#0B64DD"
}
