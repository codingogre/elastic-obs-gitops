# The release gate: the objectives a release of this service must meet, from the catalog's release block.
# The gitops-release-gate workflow reads this document by gate ID and evaluates any gate the same way.
resource "elasticgitops_release_gate" "this" {
  gate_id     = "gate-${local.name}"
  service     = local.name
  description = "Release objectives for ${local.name} (tier ${local.tier}), from catalog/services/${local.name}.yaml"
  window      = "10m"
  slo_ids = [
    elasticstack_kibana_slo.availability.slo_id,
    elasticstack_kibana_slo.latency.slo_id,
  ]

  objectives = [
    {
      name                = "error_ratio"
      max                 = local.svc.release.max_error_ratio
      compare_to_baseline = true
    },
    {
      name = "p95_ms"
      max  = local.svc.release.max_p95_ms
    },
  ]

  # Configuration releases: the most alert episodes that changed rules may open within the window.
  noisy_rule_budget = 5
}
