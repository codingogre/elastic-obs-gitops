"""Phase 0 probe B2: action policy API-key rebinding endpoint (dev, gitops-dev only).

Creates gitops-probe-api-policy-key (destination: a workflow id that does not exist, matcher on a tag no
rule carries, so it can never dispatch), calls _update_api_key, reads it back, deletes it.

    python3 scripts/with_env.py dev -- python3 tools/probe/api/probe_policy_api_key.py
"""
import json

import kb

A = "alerting_v2_action_policies"
SPACE = "gitops-dev"
PID = "gitops-probe-api-policy-key"
BASE = "/api/alerting/v2/action_policies"
BODY = {
    "name": "gitops-probe-api policy key probe",
    "description": "Temporary probe object. Safe to delete.",
    "destinations": [{"type": "workflow", "id": "gitops-probe-api-no-such-wf"}],
    "matcher": {"tags": ["gitops-probe-api-never-matches"]},
    "grouping_mode": "per_episode",
    "throttle": {"strategy": "on_status_change"},
}


def main():
    try:
        st, created = kb.fire(A, "40_put_create_for_api_key", "PUT", f"{BASE}/{PID}", body=BODY, space=SPACE, limit=300)
        kb.fire(A, "41_update_api_key", "POST", f"{BASE}/{PID}/_update_api_key", space=SPACE,
                note="Rebinds the policy to the caller's API key", limit=500)
        st, after = kb.call("GET", f"{BASE}/{PID}", space=SPACE)[:2]
        for k in ("auth", "version", "updated_at"):
            print(f"  {k}: before={json.dumps(kb.sanitize({k: created.get(k)})[k])} after={json.dumps(kb.sanitize({k: after.get(k)})[k])}")
        kb.save(A, "42_get_after_update_api_key", "GET", f"{BASE}/{PID}", st, after, space=SPACE)
        kb.fire(A, "43_put_no_matcher_expression", "PUT", f"{BASE}/{PID}",
                body=dict(BODY, matcher={"tags": ["gitops-probe-api-never-matches"], "expression": None}), space=SPACE,
                note="matcher.expression explicitly null", limit=600)
    finally:
        print("delete:", kb.call("DELETE", f"{BASE}/{PID}", space=SPACE)[0], "GET:", kb.call("GET", f"{BASE}/{PID}", space=SPACE)[0])


if __name__ == "__main__":
    main()
