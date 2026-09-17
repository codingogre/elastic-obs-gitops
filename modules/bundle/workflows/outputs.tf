output "workflow_ids" {
  description = "Workflow IDs by purpose."
  value = {
    release_gate      = "gitops-release-gate"
    remediate_service = "gitops-remediate-service"
    sync_to_git       = "gitops-sync-to-git"
    post_card         = "gitops-post-card"
  }
}
