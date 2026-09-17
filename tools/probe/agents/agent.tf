# elasticstack_kibana_agentbuilder_agent (schema, provider 0.16.5):
#   agent_id      "string" required
#   name          "string" required
#   description   "string" optional
#   instructions  "string" optional :: system instructions
#   tools         ["set","string"] optional :: tool IDs the agent can use
#   skill_ids     ["set","string"] optional :: skill IDs (Elastic Stack 9.4.0 or later)
#   labels        ["set","string"] optional
#   avatar_color, avatar_symbol "string" optional,computed
#   space_id      "string" optional,computed
#   id            "string" computed :: `<space_id>/<agent_id>`
# There is no connector or model attribute: the agent uses the space's default LLM connector.
resource "elasticstack_kibana_agentbuilder_agent" "probe" {
  space_id     = var.space_id
  agent_id     = "gitops-probe-tf-agent"
  name         = "gitops-probe-tf-agent"
  description  = "Phase 0 probe agent managed by Terraform."
  instructions = "You are a probe agent (v2). Answer briefly. Use tools only when asked about service data."
  labels       = ["gitops-probe-tf"]

  tools = [
    elasticstack_kibana_agentbuilder_tool.span_count.tool_id,
    elasticstack_kibana_agentbuilder_tool.run_workflow.tool_id,
  ]
  skill_ids = [elasticstack_kibana_agentbuilder_skill.probe.skill_id]
}
