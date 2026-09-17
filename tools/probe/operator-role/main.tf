# Throwaway probe: the gitops-operator role shape (modules/bundle/foundation/roles.tf) under a probe name, applied to
# dev and then destroyed. Proves create, a clean second plan and destroy. Local state.
#
#   python3 scripts/with_env.py dev -- terraform -chdir=tools/probe/operator-role init
#   python3 scripts/with_env.py dev -- terraform -chdir=tools/probe/operator-role apply
#   python3 scripts/with_env.py dev -- terraform -chdir=tools/probe/operator-role plan -detailed-exitcode
#   python3 scripts/with_env.py dev -- terraform -chdir=tools/probe/operator-role destroy
terraform {
  required_version = ">= 1.11.0"

  required_providers {
    elasticstack = {
      source  = "elastic/elasticstack"
      version = "0.16.5"
    }
  }
}

provider "elasticstack" {
  elasticsearch {
    endpoints = [var.elasticsearch_endpoint]
    api_key   = var.elasticsearch_api_key
  }

  kibana {
    endpoints = [var.kibana_endpoint]
    api_key   = var.kibana_api_key
  }
}

variable "elasticsearch_endpoint" {
  description = "Elasticsearch endpoint of the target project."
  type        = string
  sensitive   = true
}

variable "elasticsearch_api_key" {
  description = "API key for Elasticsearch."
  type        = string
  sensitive   = true
}

variable "kibana_endpoint" {
  description = "Kibana endpoint of the target project."
  type        = string
  sensitive   = true
}

variable "kibana_api_key" {
  description = "API key for Kibana."
  type        = string
  sensitive   = true
}

variable "space_id" {
  description = "Kibana space the role's feature privileges apply to."
  type        = string
}

resource "elasticstack_kibana_security_role" "operator" {
  name        = "gitops-probe-operator"
  description = "Probe: read-only dashboards, Discover and APM; editable SLOs and alerting."

  elasticsearch {
    indices {
      names      = ["traces-*", "logs-*", "metrics-*", "gitops-events*"]
      privileges = ["read", "view_index_metadata"]
    }

    indices {
      names      = [".slo-observability.*"]
      privileges = ["read", "view_index_metadata", "write", "manage"]
    }

    indices {
      names      = [".rule-events", ".alert-actions"]
      privileges = ["read", "view_index_metadata", "create_doc"]
    }
  }

  kibana {
    spaces = [var.space_id]

    feature {
      name       = "dashboard_v2"
      privileges = ["read"]
    }

    feature {
      name       = "discover_v2"
      privileges = ["read"]
    }

    feature {
      name       = "apm"
      privileges = ["read"]
    }

    feature {
      name       = "slo"
      privileges = ["all"]
    }

    feature {
      name       = "observabilityAlerts"
      privileges = ["all"]
    }

    feature {
      name       = "alerting_v2_rules"
      privileges = ["all"]
    }

    feature {
      name       = "alerting_v2_alerts"
      privileges = ["all"]
    }

    feature {
      name       = "alerting_v2_action_policies"
      privileges = ["read"]
    }

    feature {
      name       = "alerting_v2_execution_history"
      privileges = ["read"]
    }
  }
}
