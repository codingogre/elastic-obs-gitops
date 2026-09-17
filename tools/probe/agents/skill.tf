# elasticstack_kibana_agentbuilder_skill (schema, provider 0.16.5):
#   skill_id           "string" required :: Required; the API does not auto-generate skill IDs.
#   name               "string" required
#   description        "string" required
#   content            "string" required :: Skill instructions content as markdown.
#   tool_ids           ["set","string"] optional :: tool IDs from the tool registry that this skill references.
#   referenced_content nested list optional :: {name, relative_path ("./..."), content}, up to 100, ordered
#   space_id           "string" optional,computed
#   id                 "string" computed :: `<space_id>/<skill_id>`
resource "elasticstack_kibana_agentbuilder_skill" "probe" {
  space_id    = var.space_id
  skill_id    = "gitops-probe-tf-skill"
  name        = "gitops-probe-tf-skill"
  description = "Probe skill: how to answer questions about service load."
  content     = file("${path.module}/assets/probe-skill.md")
  tool_ids    = [elasticstack_kibana_agentbuilder_tool.span_count.tool_id]
}
