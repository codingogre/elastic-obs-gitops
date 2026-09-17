# Platform workflows: release gate, remediation, sync to Git, post card. See docs/CONVENTIONS.md.
#
# Each workflow is a YAML file next to this one, loaded with file() so the stored definition is byte-identical to
# Git (the capture flow relies on that). Connector IDs in the YAML are the fixed UUIDs from var.connector_ids,
# which are the same in every environment.

locals {
  workflows = {
    release_gate      = { id = "gitops-release-gate", file = "release-gate.yaml" }
    remediate_service = { id = "gitops-remediate-service", file = "remediate-service.yaml" }
    sync_to_git       = { id = "gitops-sync-to-git", file = "sync-to-git.yaml" }
    post_card         = { id = "gitops-post-card", file = "post-card.yaml" }
  }
}

resource "elasticstack_kibana_agentbuilder_workflow" "this" {
  for_each = local.workflows

  space_id           = var.space_id
  workflow_id        = each.value.id
  configuration_yaml = file("${path.module}/${each.value.file}")

  lifecycle {
    precondition {
      condition = alltrue([
        for m in regexall("connector-id: ([0-9a-f-]{36})", file("${path.module}/${each.value.file}")) :
        contains(values(var.connector_ids), m[0])
      ])
      error_message = "${each.value.file} uses a connector UUID that is not in var.connector_ids (docs/CONVENTIONS.md)."
    }
  }
}
