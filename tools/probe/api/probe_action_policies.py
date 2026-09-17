"""Phase 0 probe B: Workflows create API + Alerting v2 action policy API shapes (dev, gitops-dev only).

Creates gitops-probe-api-wf (workflow), gitops-probe-api-rule (v2 rule, disabled right away) and
gitops-probe-api-policy (action policy) in gitops-dev, and removes all three at the end.

    python3 scripts/with_env.py dev -- python3 tools/probe/api/probe_action_policies.py
"""
import copy
import json
import time

import kb

SPACE = "gitops-dev"
WF = "gitops-probe-api-wf"
RID = "gitops-probe-api-rule"
PID = "gitops-probe-api-policy"
MATCH_TAG = "gitops-probe-api-policy-match"
RULES = "/api/alerting/v2/rules"
POL = "/api/alerting/v2/action_policies"
WFP = "/api/workflows/workflow"

WF_MINIMAL = """name: gitops-probe-api workflow (Phase 0 API probe)
enabled: true
description: Temporary probe object. Safe to delete.
tags:
  - gitops-probe-api
triggers:
  - type: manual
steps:
  - name: log
    type: console
    with:
      message: gitops-probe-api
"""

WF_V2_INPUT = """name: gitops-probe-api workflow (Phase 0 API probe)
enabled: true
description: Temporary probe object. Safe to delete.
tags:
  - gitops-probe-api
triggers:
  - type: manual
    inputs:
      type: object
      properties:
        payload:
          $ref: "#/kibana/definitions/alertingV2NotificationGroup"
      required:
        - payload
steps:
  - name: log
    type: console
    with:
      message: "gitops-probe-api {{ inputs.payload.episodes[0].episode_id }}"
"""

RULE = {
    "kind": "alert",
    "metadata": {"name": "gitops-probe-api rule (policy probe)", "description": "Temporary probe object. Safe to delete.",
                 "tags": [MATCH_TAG, "gitops-probe-api"]},
    "time_field": "@timestamp",
    "schedule": {"every": "5m", "lookback": "5m"},
    "query": {"format": "standalone",
              "breach": {"query": 'FROM traces-* | WHERE service.name == "gitops-probe-api-none" | STATS n = COUNT(*) | WHERE n > 0'}},
    "recovery_strategy": "no_breach",
    "state_transition": {"pending_count": 0, "recovering_count": 0},
}

POLICY = {
    "name": "gitops-probe-api policy (Phase 0 API probe)",
    "description": "Temporary probe object. Safe to delete.",
    "destinations": [{"type": "workflow", "id": WF}],
    "matcher": {"tags": [MATCH_TAG], "expression": 'episode_status : "active" or episode_status : "inactive"'},
    "tags": ["gitops-probe-api"],
    "grouping_mode": "per_episode",
    "throttle": {"strategy": "on_status_change"},
}


def section(t):
    print(f"\n===== {t} =====")


def workflows():
    section("Workflows API")
    A = "workflows"
    kb.fire(A, "00_get_missing", "GET", f"{WFP}/{WF}", space=SPACE)
    st, wf = kb.fire(A, "01_post_create_with_id", "POST", WFP, body={"id": WF, "yaml": WF_MINIMAL}, space=SPACE,
                     note="Create with a caller-chosen id (body.id)")
    if st != 200:
        raise SystemExit("workflow create failed")
    kb.fire(A, "02_get", "GET", f"{WFP}/{WF}", space=SPACE)
    kb.fire(A, "03_post_create_duplicate_id", "POST", WFP, body={"id": WF, "yaml": WF_MINIMAL}, space=SPACE,
            note="Same id again", limit=600)
    kb.fire(A, "04_get_from_default_space", "GET", f"{WFP}/{WF}", space="default", limit=400)
    kb.fire(A, "05_post_invalid_id", "POST", WFP, body={"id": "Gitops_Probe_Api_Bad", "yaml": WF_MINIMAL}, space=SPACE,
            note="Id outside ^[a-z0-9]([a-z0-9-]*[a-z0-9])?$", limit=600)
    return wf


def policy_probe():
    A = "alerting_v2_action_policies"
    section("Action policies")
    st, body, el, _ = kb.call("GET", POL, space="default")
    items = body.get("items", []) if isinstance(body, dict) else []
    kb.save(A, "00_list_default_space_fieldnames", "GET", POL, st,
            {"top_level_keys": sorted(body.keys()) if isinstance(body, dict) else body, "item_count": len(items),
             "item_field_names": sorted({k for i in items for k in i.keys()}),
             "note": "Pre-existing policies belong to another demo: only field names are recorded."}, elapsed=el)
    print(f"--- list default: HTTP {st} items={len(items)} probe_present={PID in [i.get('id') for i in items]}")
    kb.fire(A, "01_list_gitops_dev_before", "GET", POL, space=SPACE, limit=400)
    kb.fire(A, "02_get_missing", "GET", f"{POL}/{PID}", space=SPACE)

    bad = dict(POLICY, destinations=[{"type": "workflow", "id": "gitops-probe-api-no-such-wf"}])
    st, _ = kb.fire(A, "03_put_missing_workflow", "PUT", f"{POL}/{PID}", body=bad, space=SPACE,
                    note="Destination workflow does not exist", limit=600)
    if st in (200, 201):
        kb.call("DELETE", f"{POL}/{PID}", space=SPACE)

    st, created = kb.fire(A, "04_put_create", "PUT", f"{POL}/{PID}", body=POLICY, space=SPACE,
                          note="Create (upsert) with caller-chosen id; destination workflow has a bare manual trigger")
    if st not in (200, 201):
        raise SystemExit("policy create failed")
    print("order sent:", list(POLICY.keys()))
    print("order got :", list(created.keys()))
    st, got = kb.fire(A, "05_get", "GET", f"{POL}/{PID}", space=SPACE)

    time.sleep(1.2)
    st, same = kb.fire(A, "06_put_identical", "PUT", f"{POL}/{PID}", body=POLICY, space=SPACE,
                       note="Identical body again: does version/updated_at change?", limit=600)
    for k in ("version", "updated_at"):
        print(f"  no-op PUT {k}: before={got.get(k)} after={same.get(k) if isinstance(same, dict) else same}")

    upd = copy.deepcopy(POLICY)
    upd["throttle"] = {"strategy": "per_status_interval", "interval": "5m"}
    upd["matcher"]["expression"] = 'episode_status : "active"'
    kb.fire(A, "07_put_update", "PUT", f"{POL}/{PID}", body=upd, space=SPACE, limit=800)
    kb.fire(A, "08_get_after_update", "GET", f"{POL}/{PID}", space=SPACE, limit=800)

    minimal = {k: POLICY[k] for k in ("name", "description", "destinations")}
    kb.fire(A, "09_put_minimal", "PUT", f"{POL}/{PID}", body=minimal, space=SPACE,
            note="Only the required fields: which defaults does the server fill in?", limit=1200)

    no_tags = {k: v for k, v in POLICY.items() if k != "tags"}
    kb.fire(A, "10_put_without_policy_tags", "PUT", f"{POL}/{PID}", body=no_tags, space=SPACE, limit=500)

    st, cur = kb.fire(A, "11_put_restore", "PUT", f"{POL}/{PID}", body=POLICY, space=SPACE, limit=300)
    for field in ("id", "enabled", "version", "auth", "created_by", "created_at", "updated_by", "updated_at",
                  "group_by", "snoozed_until"):
        if isinstance(cur, dict) and field in cur:
            kb.fire(A, f"12_put_with_response_field_{field}", "PUT", f"{POL}/{PID}", body=dict(POLICY, **{field: cur[field]}),
                    space=SPACE, note=f"Round-trip the server field '{field}' in PUT", limit=400)
    kb.fire(A, "12b_put_restore", "PUT", f"{POL}/{PID}", body=POLICY, space=SPACE, limit=200)

    st, cur = kb.call("GET", f"{POL}/{PID}", space=SPACE)[:2]
    kb.fire(A, "13_patch_without_version", "PATCH", f"{POL}/{PID}", body={"description": "patched"}, space=SPACE, limit=500)
    kb.fire(A, "14_patch_stale_version", "PATCH", f"{POL}/{PID}", body={"description": "patched", "version": "WzEsMV0="},
            space=SPACE, limit=500)
    kb.fire(A, "15_patch_current_version", "PATCH", f"{POL}/{PID}", body={"description": "patched", "version": cur.get("version")},
            space=SPACE, limit=500)
    kb.fire(A, "15b_put_restore", "PUT", f"{POL}/{PID}", body=POLICY, space=SPACE, limit=200)

    # Space awareness.
    kb.fire(A, "16_get_from_default_space", "GET", f"{POL}/{PID}", space="default", limit=400)
    st, body = kb.call("GET", POL, space="default")[:2]
    print("  probe policy in default-space list:", PID in [i.get("id") for i in (body or {}).get("items", [])])

    # Enable / disable.
    kb.fire(A, "17_disable", "POST", f"{POL}/{PID}/_disable", space=SPACE, limit=500)
    st, p = kb.fire(A, "18_put_while_disabled", "PUT", f"{POL}/{PID}", body=POLICY, space=SPACE, limit=200)
    print("  enabled after PUT while disabled:", p.get("enabled") if isinstance(p, dict) else p)
    kb.fire(A, "19_enable", "POST", f"{POL}/{PID}/_enable", space=SPACE, limit=300)

    # Destination workflow: with the alertingV2NotificationGroup input, then disabled.
    st, _ = kb.fire("workflows", "10_put_update_yaml_v2_input", "PUT", f"{WFP}/{WF}", body={"yaml": WF_V2_INPUT},
                    space=SPACE, note="Update the YAML to take the alertingV2NotificationGroup payload", limit=800)
    kb.fire(A, "20_put_after_wf_v2_input", "PUT", f"{POL}/{PID}", body=POLICY, space=SPACE, limit=200)
    kb.fire("workflows", "11_put_disable", "PUT", f"{WFP}/{WF}", body={"enabled": False}, space=SPACE,
            note="PUT with only enabled=false", limit=800)
    kb.fire(A, "21_put_with_disabled_workflow", "PUT", f"{POL}/{PID}", body=POLICY, space=SPACE,
            note="Destination workflow is disabled", limit=600)
    kb.fire("workflows", "12_put_enable", "PUT", f"{WFP}/{WF}", body={"enabled": True}, space=SPACE, limit=300)

    kb.fire(A, "90_delete", "DELETE", f"{POL}/{PID}", space=SPACE)
    kb.fire(A, "91_get_after_delete", "GET", f"{POL}/{PID}", space=SPACE)
    kb.fire(A, "92_delete_again", "DELETE", f"{POL}/{PID}", space=SPACE)


def rule_extras():
    A = "alerting_v2_rules"
    section("Rule extras")
    st, r = kb.fire(A, "30_put_create_for_policy", "PUT", f"{RULES}/{RID}", body=RULE, space=SPACE, limit=300)
    kb.fire(A, "31_disable_immediately", "POST", f"{RULES}/{RID}/_disable", space=SPACE, limit=200)
    body = dict(RULE, metadata=dict(RULE["metadata"], owner="gitops-probe-owner"))
    st, r = kb.call("PUT", f"{RULES}/{RID}", body=body, space=SPACE)[:2]
    print("  metadata.owner echoed:", r.get("metadata", {}).get("owner"))
    st, r = kb.call("PUT", f"{RULES}/{RID}", body=RULE, space=SPACE)[:2]
    print("  metadata.owner after PUT without owner:", r.get("metadata", {}).get("owner", "<absent>"))
    reordered = dict(reversed(list(RULE.items())))
    st, r = kb.call("PUT", f"{RULES}/{RID}", body=reordered, space=SPACE)[:2]
    print("  key order with reversed request:", list(r.keys()))
    kb.fire(A, "32_patch_without_version", "PATCH", f"{RULES}/{RID}", body={"schedule": {"every": "10m"}}, space=SPACE, limit=300)
    kb.fire(A, "33_patch_stale_version", "PATCH", f"{RULES}/{RID}", body={"schedule": {"every": "10m"}, "version": "WzEsMV0="},
            space=SPACE, limit=500)
    st, g = kb.call("GET", f"{RULES}/{RID}", space=SPACE)[:2]
    kb.fire(A, "34_patch_current_version", "PATCH", f"{RULES}/{RID}", body={"schedule": {"every": "10m", "lookback": "5m"}, "version": g.get("version")},
            space=SPACE, limit=500)
    kb.fire(A, "35_run_while_disabled", "POST", f"{RULES}/{RID}/_run", space=SPACE, limit=500)
    kb.fire(A, "36_put_invalid_esql", "PUT", f"{RULES}/{RID}", body=dict(RULE, query={"format": "standalone", "breach": {"query": "FROM traces-* | WHER x"}}),
            space=SPACE, note="Syntactically invalid ES|QL", limit=600)
    kb.fire(A, "37_put_invalid_duration", "PUT", f"{RULES}/{RID}", body=dict(RULE, schedule={"every": "1 minute"}),
            space=SPACE, note="Invalid duration format", limit=600)


def cleanup_workflow():
    section("Workflow delete (hard)")
    A = "workflows"
    kb.fire(A, "90_delete_force", "DELETE", f"{WFP}/{WF}?force=true", space=SPACE)
    kb.fire(A, "91_get_after_delete", "GET", f"{WFP}/{WF}", space=SPACE, limit=400)
    st, _ = kb.fire(A, "92_recreate_same_id_after_force_delete", "POST", WFP, body={"id": WF, "yaml": WF_MINIMAL}, space=SPACE,
                    note="Is the id reusable after a hard delete?", limit=400)
    if st == 200:
        kb.fire(A, "93_delete_force_again", "DELETE", f"{WFP}/{WF}?force=true", space=SPACE)
    kb.fire(A, "94_get_final", "GET", f"{WFP}/{WF}", space=SPACE, limit=400)
    for other in ("Gitops_Probe_Api_Bad", "gitops_probe_api_bad"):
        if kb.call("GET", f"{WFP}/{other}", space=SPACE)[0] == 200:
            print("cleanup invalid-id workflow:", kb.call("DELETE", f"{WFP}/{other}?force=true", space=SPACE)[0])


def main():
    try:
        workflows()
        rule_extras()
        policy_probe()
    finally:
        section("Cleanup")
        st = kb.call("DELETE", f"{POL}/{PID}", space=SPACE)[0]
        print("policy delete:", st, "GET:", kb.call("GET", f"{POL}/{PID}", space=SPACE)[0])
        st = kb.call("DELETE", f"{RULES}/{RID}", space=SPACE)[0]
        print("rule delete:", st, "GET:", kb.call("GET", f"{RULES}/{RID}", space=SPACE)[0])
        cleanup_workflow()


if __name__ == "__main__":
    main()
