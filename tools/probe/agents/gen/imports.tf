# generate-config-out probe (local state, plan only; nothing is applied from here).
import {
  to = elasticstack_kibana_agentbuilder_workflow.probe
  id = "gitops-dev/gitops-probe-tf-workflow"
}

import {
  to = elasticstack_kibana_agentbuilder_agent.probe
  id = "gitops-dev/gitops-probe-tf-agent"
}

import {
  to = elasticstack_kibana_agentbuilder_tool.span_count
  id = "gitops-dev/gitops-probe-tf-span-count"
}

import {
  to = elasticstack_kibana_agentbuilder_tool.run_workflow
  id = "gitops-dev/gitops-probe-tf-run-workflow"
}

import {
  to = elasticstack_kibana_agentbuilder_skill.probe
  id = "gitops-dev/gitops-probe-tf-skill"
}

import {
  to = elasticstack_kibana_action_connector.servicenow
  id = "gitops-dev/0ac439ee-e2c3-4336-a849-62a6247c5fc3"
}
