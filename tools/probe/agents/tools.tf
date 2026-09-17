# elasticstack_kibana_agentbuilder_tool (schema, provider 0.16.5):
#   tool_id       "string" required :: The tool ID.
#   type          "string" required :: Must be one of: [esql index_search workflow mcp].
#   configuration "string" required :: The tool configuration as a JSON-encoded string.
#   description   "string" optional
#   tags          ["set","string"] optional
#   space_id      "string" optional,computed
#   id            "string" computed :: `<space_id>/<tool_id>`
resource "elasticstack_kibana_agentbuilder_tool" "span_count" {
  space_id    = var.space_id
  tool_id     = "gitops-probe-tf-span-count"
  type        = "esql"
  description = "Counts trace spans for one service over the last hour (v2). Use when asked how busy a service is."
  tags        = ["gitops-probe-tf"]

  configuration = jsonencode({
    query = trimspace(file("${path.module}/assets/probe-tool.esql"))
    params = {
      service = {
        type        = "string"
        description = "Service name, for example grid-dispatch"
      }
    }
  })
}

resource "elasticstack_kibana_agentbuilder_tool" "run_workflow" {
  space_id    = var.space_id
  tool_id     = "gitops-probe-tf-run-workflow"
  type        = "workflow"
  description = "Runs the probe workflow, which only logs the service name."
  tags        = ["gitops-probe-tf"]

  configuration = jsonencode({
    workflow_id = elasticstack_kibana_agentbuilder_workflow.probe.workflow_id
  })
}
