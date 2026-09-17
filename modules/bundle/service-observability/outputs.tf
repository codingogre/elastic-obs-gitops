output "health_tool_id" {
  description = "Agent Builder ES|QL tool for the SRE agent. Referencing the resource makes agents wait for the tool."
  value       = elasticstack_kibana_agentbuilder_tool.health.tool_id
}

output "dashboard_id" {
  value = elasticstack_kibana_dashboard.golden_signals.dashboard_id
}

output "slo_ids" {
  value = {
    availability = elasticstack_kibana_slo.availability.slo_id
    latency      = elasticstack_kibana_slo.latency.slo_id
  }
}

output "burn_rate_rule_ids" {
  value = {
    availability = elasticstack_kibana_alerting_rule.availability_burn_rate.rule_id
    latency      = elasticstack_kibana_alerting_rule.latency_burn_rate.rule_id
  }
}

output "gate_id" {
  value = elasticgitops_release_gate.this.gate_id
}
