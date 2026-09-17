"""Phase 0 probe C2: dashboard access_control through an API key (dev, gitops-dev only).

PUT with access_control.access_mode=write_restricted returned HTTP 500 in probe_dashboards.py.
This narrows it down. Every object is deleted at the end.

    python3 scripts/with_env.py dev -- python3 tools/probe/api/probe_dashboards_access.py
"""
import json

import kb

A = "dashboards"
SPACE = "gitops-dev"
BASE = "/api/dashboards"
D1 = "gitops-probe-api-dash-ac-default"
D2 = "gitops-probe-api-dash-ac-update"
BODY = {"title": "gitops-probe-api access probe", "description": "Temporary probe object. Safe to delete.", "panels": []}


def main():
    post_ids = []
    try:
        kb.fire(A, "30_put_create_access_mode_default", "PUT", f"{BASE}/{D1}",
                body=dict(BODY, access_control={"access_mode": "default"}), space=SPACE,
                note="access_control.access_mode=default on create (API key auth)", limit=800)
        kb.fire(A, "31_put_create_plain", "PUT", f"{BASE}/{D2}", body=BODY, space=SPACE, limit=400)
        kb.fire(A, "32_put_update_to_write_restricted", "PUT", f"{BASE}/{D2}",
                body=dict(BODY, access_control={"access_mode": "write_restricted"}), space=SPACE,
                note="Switch an existing dashboard to write_restricted (API key auth)", limit=800)
        st, p = kb.fire(A, "33_post_create_write_restricted", "POST", BASE,
                        body=dict(BODY, access_control={"access_mode": "write_restricted"}), space=SPACE,
                        note="POST create with write_restricted (API key auth)", limit=800)
        if st in (200, 201) and isinstance(p, dict):
            post_ids.append(p["id"])
        st, g = kb.call("GET", f"{BASE}/{D2}", space=SPACE)[:2]
        print("D2 access_control:", json.dumps((g.get("data") or {}).get("access_control")) if isinstance(g, dict) else g)
        print("D2 meta keys:", list((g.get("meta") or {}).keys()) if isinstance(g, dict) else g)
        # Identity behind the API key: does it have a user profile?
        st, me, _, _ = kb.call("GET", "/internal/security/me", internal=True)
        if isinstance(me, dict):
            print("security/me: HTTP", st, "keys:", sorted(me.keys()),
                  "authentication_type:", me.get("authentication_type"),
                  "has profile_uid:", bool(me.get("profile_uid")))
        else:
            print("security/me: HTTP", st)
        st, prof, _, _ = kb.call("GET", "/internal/security/user_profile", internal=True)
        print("user_profile: HTTP", st, "type:", type(prof).__name__)
        kb.save(A, "34_security_me_shape", "GET", "/internal/security/me", st,
                {"http_status_user_profile": st, "me_keys": sorted(me.keys()) if isinstance(me, dict) else None,
                 "authentication_type": me.get("authentication_type") if isinstance(me, dict) else None,
                 "has_profile_uid": bool(me.get("profile_uid")) if isinstance(me, dict) else None},
                note="Shape only: does the Terraform API key identity carry a user profile (needed as dashboard owner)?")
        st, lst = kb.call("GET", f"{BASE}?query=gitops-probe-api&per_page=5", space=SPACE)[:2]
        if isinstance(lst, dict):
            items = lst.get("data") or []
            print("list: top keys", list(lst.keys()), "meta", lst.get("meta"),
                  "item keys", list(items[0].keys()) if items else None,
                  "item.data keys", list((items[0].get("data") or {}).keys()) if items else None)
            kb.save(A, "35_list_shape", "GET", f"{BASE}?query=gitops-probe-api&per_page=5", st, lst, space=SPACE)
    finally:
        print("\n===== Cleanup =====")
        for did in [D1, D2] + post_ids:
            st = kb.call("DELETE", f"{BASE}/{did}", space=SPACE)[0]
            print(did, "DELETE", st, "GET", kb.call("GET", f"{BASE}/{did}", space=SPACE)[0])
        st, lst = kb.call("GET", f"{BASE}?query=gitops-probe-api&per_page=50", space=SPACE)[:2]
        left = [d.get("id") for d in lst.get("data", [])] if isinstance(lst, dict) else lst
        print("remaining gitops-probe-api dashboards (search):", left)


if __name__ == "__main__":
    main()
