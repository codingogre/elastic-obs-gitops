# gitops-gates: one document per release gate (gate-<service>), written by elasticgitops_release_gate
# and read by the release-gate workflow.
resource "elasticstack_elasticsearch_index_template" "gitops_gates" {
  name           = "gitops-gates"
  index_patterns = ["gitops-gates"]
  priority       = 500

  template {
    mappings = jsonencode({
      dynamic = false
      properties = {
        gate_id           = { type = "keyword" }
        service           = { type = "keyword" }
        description       = { type = "text" }
        window            = { type = "keyword" }
        slo_ids           = { type = "keyword" }
        noisy_rule_budget = { type = "long" }
        updated_at        = { type = "date" }
        objectives = {
          properties = {
            name                = { type = "keyword" }
            max                 = { type = "double" }
            compare_to_baseline = { type = "boolean" }
          }
        }
      }
    })
  }
}
