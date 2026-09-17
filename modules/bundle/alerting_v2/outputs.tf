output "rule_ids" {
  value = { for k, r in elasticgitops_alerting_v2_rule.error_spike : k => r.rule_id }
}

output "policy_id" {
  value = elasticgitops_alerting_v2_action_policy.remediation.policy_id
}
