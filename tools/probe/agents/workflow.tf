# elasticstack_kibana_agentbuilder_workflow (schema, provider 0.16.5):
#   configuration_yaml "string" required :: The YAML configuration for the workflow.
#   workflow_id        "string" optional,computed :: If not provided, it will be auto-generated. IDs are `workflow-<UUIDv4>`.
#   space_id           "string" optional,computed
#   id                 "string" computed :: The composite ID of the workflow: `<space_id>/<workflow_id>`.
#   name, description, enabled, valid: computed (extracted from the YAML)
resource "elasticstack_kibana_agentbuilder_workflow" "probe" {
  space_id           = var.space_id
  workflow_id        = "gitops-probe-tf-workflow"
  configuration_yaml = file("${path.module}/assets/probe-workflow.yaml")
}
