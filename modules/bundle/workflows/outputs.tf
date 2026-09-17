output "workflow_ids" {
  description = "Workflow IDs by purpose."
  value = {
    release_gate      = elasticstack_kibana_agentbuilder_workflow.this["release_gate"].workflow_id
    remediate_service = elasticstack_kibana_agentbuilder_workflow.this["remediate_service"].workflow_id
    sync_to_git       = elasticstack_kibana_agentbuilder_workflow.this["sync_to_git"].workflow_id
    post_card         = elasticstack_kibana_agentbuilder_workflow.this["post_card"].workflow_id
  }
}
