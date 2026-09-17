# gitops-operator: the role people get in an environment where Git owns the configuration
# (settings.operator_role). Dashboards stay read-only; SLOs and alerting stay editable, so a hand edit is possible
# and drift detection reverts it. Roles are project-wide, and people receive this one as an Elastic Cloud project role
# (Organization > Members), not through Terraform.
#
# Feature IDs are the ones GET /api/features lists on 9.6 Serverless Observability. There, dashboard_v2 is composed of
# the hidden visualize_v2 and maps_v2 features, so dashboard read also grants visualizations and maps read.
resource "elasticstack_kibana_security_role" "operator" {
  count = var.settings.operator_role ? 1 : 0

  name        = "gitops-operator"
  description = "Read-only dashboards, Discover and APM; editable SLOs and alerting. Configuration is managed from Git."

  elasticsearch {
    # Telemetry and GitOps events, for Discover, APM and dashboards. SLO edits also check read and
    # view_index_metadata on the SLO's source index (metrics-*.otel-*).
    indices {
      names      = ["traces-*", "logs-*", "metrics-*", "gitops-events*"]
      privileges = ["read", "view_index_metadata"]
    }

    # SLO editor (Elastic docs, "Configure SLO access"). An edit re-installs the SLO's pipelines and transforms with
    # the user as secondary authorization, writes summary documents and deletes the old revision's data as the user.
    # No cluster privileges are needed.
    indices {
      names      = [".slo-observability.*"]
      privileges = ["read", "view_index_metadata", "write", "manage"]
    }

    # Alerting v2 reads episodes from .rule-events and writes acknowledgements to .rule-events and .alert-actions as
    # the signed-in user.
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

    # Includes the SLO burn-rate rules.
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

    # Read-only: saving an action policy rebinds its dispatch to the saver's credentials.
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
