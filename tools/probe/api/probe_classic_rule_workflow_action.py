"""Phase 0 probe F2 (Q2): a classic rule whose action runs a workflow (dev, gitops-dev only).

Creates workflow gitops-probe-api-wf2 and a DISABLED .es-query rule gitops-probe-api-classic-rule with
one system action (system-connector-.workflows), reads the rule back, then deletes both.

    python3 scripts/with_env.py dev -- python3 tools/probe/api/probe_classic_rule_workflow_action.py
"""
import kb

A = "classic_rule_workflow_action"
SPACE = "gitops-dev"
WF = "gitops-probe-api-wf2"
RID = "gitops-probe-api-classic-rule"
WF_YAML = """name: gitops-probe-api classic-rule target (Phase 0 API probe)
enabled: true
description: Temporary probe object. Safe to delete.
tags:
  - gitops-probe-api
triggers:
  - type: alert
steps:
  - name: log
    type: console
    with:
      message: "gitops-probe-api alert {{ event.alerts[0]._id }}"
"""


def rule_body(with_group):
    action = {"id": "system-connector-.workflows",
              "params": {"subAction": "run", "subActionParams": {"workflowId": WF, "summaryMode": True}}}
    if with_group:
        action["group"] = "query matched"
    return {
        "name": "gitops-probe-api classic rule (Phase 0 API probe)",
        "rule_type_id": ".es-query",
        "consumer": "logs",
        "enabled": False,
        "tags": ["gitops-probe-api"],
        "schedule": {"interval": "10m"},
        "params": {
            "searchType": "esqlQuery",
            "esqlQuery": {"esql": 'FROM traces-* | WHERE service.name == "gitops-probe-api-none" | KEEP @timestamp | LIMIT 1'},
            "timeWindowSize": 5, "timeWindowUnit": "m", "threshold": [0], "thresholdComparator": ">",
            "size": 100, "aggType": "count", "groupBy": "all", "excludeHitsFromPreviousRun": True, "timeField": "@timestamp",
        },
        "actions": [action],
    }


def main():
    try:
        st, wf = kb.fire(A, "01_create_workflow_alert_trigger", "POST", "/api/workflows/workflow",
                         body={"id": WF, "yaml": WF_YAML}, space=SPACE, note="Workflow with an alert trigger", limit=500)
        if st != 200:
            kb.fire(A, "01b_create_workflow_manual_trigger", "POST", "/api/workflows/workflow",
                    body={"id": WF, "yaml": WF_YAML.replace("type: alert", "type: manual").replace("{{ event.alerts[0]._id }}", "")},
                    space=SPACE, limit=500)
        st, r = kb.fire(A, "02_create_rule_system_action_no_group", "POST", f"/api/alerting/rule/{RID}", body=rule_body(False),
                        space=SPACE, note="Classic .es-query rule (disabled) with a Workflows system action, no group", limit=2500)
        if st not in (200, 201):
            st, r = kb.fire(A, "02b_create_rule_system_action_with_group", "POST", f"/api/alerting/rule/{RID}", body=rule_body(True),
                            space=SPACE, note="Same with group", limit=2500)
        kb.fire(A, "03_get_rule", "GET", f"/api/alerting/rule/{RID}", space=SPACE, limit=2500)
    finally:
        print("\n===== Cleanup =====")
        kb.fire(A, "90_delete_rule", "DELETE", f"/api/alerting/rule/{RID}", space=SPACE, limit=300)
        print("rule GET after delete:", kb.call("GET", f"/api/alerting/rule/{RID}", space=SPACE)[0])
        kb.fire(A, "91_delete_workflow_force", "DELETE", f"/api/workflows/workflow/{WF}?force=true", space=SPACE, limit=300)
        print("workflow GET after delete:", kb.call("GET", f"/api/workflows/workflow/{WF}", space=SPACE)[0])


if __name__ == "__main__":
    main()
