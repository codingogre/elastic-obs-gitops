"""Phase 0 probe A: Alerting v2 rule API shapes (dev, space gitops-dev only).

Creates exactly one rule, gitops-probe-api-rule, in gitops-dev and deletes it at the end.
Pre-existing rules are only listed; for them only field names are recorded.

    python3 scripts/with_env.py dev -- python3 tools/probe/api/probe_alerting_v2_rules.py
"""
import copy
import json
import time

import kb

API = "alerting_v2_rules"
SPACE = "gitops-dev"
RID = "gitops-probe-api-rule"
BASE = "/api/alerting/v2/rules"
TAG = "gitops-probe-api"

BODY = {
    "kind": "alert",
    "metadata": {
        "name": "gitops-probe-api rule (Phase 0 API probe)",
        "description": "Temporary probe object. Safe to delete.",
        "tags": [TAG, "probe"],
    },
    "time_field": "@timestamp",
    "schedule": {"every": "1m", "lookback": "5m"},
    "query": {
        "format": "standalone",
        "breach": {
            "query": 'FROM traces-* | WHERE service.name == "grid-dispatch" '
                     "| STATS n = COUNT(*) | WHERE n > 0",
        },
    },
    "recovery_strategy": "no_breach",
    "state_transition": {"pending_count": 0, "recovering_count": 0},
}


def key_paths(obj, prefix=""):
    paths = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{prefix}.{k}" if prefix else k
            paths.add(p)
            paths |= key_paths(v, p)
    elif isinstance(obj, list):
        for v in obj:
            paths |= key_paths(v, prefix + "[]")
    return paths


def field_names_only(name, space):
    st, body, el, _ = kb.call("GET", BASE, space=space)
    items = body.get("items", []) if isinstance(body, dict) else []
    names = sorted(set().union(*[key_paths(i) for i in items])) if items else []
    top = sorted(k for k in body.keys()) if isinstance(body, dict) else body
    ids = [i.get("id") for i in items]
    mine = [i for i in ids if str(i).startswith("gitops-probe-api")]
    summary = {"top_level_keys": top, "total": body.get("total") if isinstance(body, dict) else None,
               "item_count": len(items), "item_field_paths": names,
               "contains_probe_rule": RID in ids,
               "note": "Pre-existing rules belong to another demo: only field names are recorded."}
    kb.save(API, name, "GET", BASE, st, summary, space=space, elapsed=el)
    print(f"--- list {space}: HTTP {st} total={summary['total']} items={len(items)} probe_rule_present={RID in ids} mine={mine}")
    return st, body, ids


def diff(a, b, prefix=""):
    """Print fields that differ between the request (a) and the response (b)."""
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in list(a.keys()) + [k for k in b.keys() if k not in a]:
            p = f"{prefix}.{k}" if prefix else k
            if k not in b:
                out.append(f"  - {p} (sent, not returned)")
            elif k not in a:
                out.append(f"  + {p} = {json.dumps(kb.sanitize({k: b[k]})[k])[:160]} (server added)")
            else:
                out += diff(a[k], b[k], p)
    elif a != b:
        out.append(f"  ~ {prefix}: sent {json.dumps(a)[:120]} got {json.dumps(kb.sanitize(b))[:120]}")
    return out


def main():
    created = False
    try:
        field_names_only("00_list_default_space_fieldnames", "default")
        field_names_only("01_list_gitops_dev_before", SPACE)

        kb.fire(API, "02_get_missing", "GET", f"{BASE}/{RID}", space=SPACE)

        # Server-managed fields in the create body.
        for field, value in (("enabled", False), ("id", RID)):
            body = dict(BODY, **{field: value})
            st, resp = kb.fire(API, f"03_put_create_with_{field}", "PUT", f"{BASE}/{RID}", body=body, space=SPACE,
                               note=f"Create with top-level '{field}' in the body")
            if st in (200, 201):
                created = True
                kb.fire(API, f"03b_delete_after_{field}", "DELETE", f"{BASE}/{RID}", space=SPACE)
                created = False

        st, resp = kb.fire(API, "04_put_create", "PUT", f"{BASE}/{RID}", body=BODY, space=SPACE,
                           note="Create (upsert) with a caller-chosen ID")
        created = st in (200, 201)
        if not created:
            raise SystemExit("create failed")
        print("order sent:", list(BODY.keys()))
        print("order got :", list(resp.keys()))
        print("diff create request -> response:")
        print("\n".join(diff(BODY, resp)))

        st, got = kb.fire(API, "05_get", "GET", f"{BASE}/{RID}", space=SPACE)
        print("diff create request -> GET:")
        print("\n".join(diff(BODY, got)))

        time.sleep(1.5)
        st, same = kb.fire(API, "06_put_identical", "PUT", f"{BASE}/{RID}", body=BODY, space=SPACE,
                           note="Identical body again: does updated_at or version change on a no-op PUT?")
        for k in ("updated_at", "version"):
            print(f"  no-op PUT {k}: before={got.get(k)} after={same.get(k)}")
        print("  metadata.version before/after:", got.get("metadata", {}).get("version"), same.get("metadata", {}).get("version"))

        upd = copy.deepcopy(BODY)
        upd["schedule"] = {"every": "2m", "lookback": "10m"}
        st, r1 = kb.fire(API, "07_put_update_schedule", "PUT", f"{BASE}/{RID}", body=upd, space=SPACE)
        kb.fire(API, "08_get_after_update", "GET", f"{BASE}/{RID}", space=SPACE)

        # Duration normalization and omitted optional fields.
        upd2 = copy.deepcopy(BODY)
        upd2["schedule"] = {"every": "120s"}
        del upd2["state_transition"]
        del upd2["time_field"]
        st, r2 = kb.fire(API, "09_put_duration_seconds_no_lookback", "PUT", f"{BASE}/{RID}", body=upd2, space=SPACE,
                         note="every=120s, lookback omitted, state_transition and time_field omitted: are they normalized or defaulted?")
        kb.fire(API, "10_get_after_duration", "GET", f"{BASE}/{RID}", space=SPACE)

        # Restore the canonical body.
        st, cur = kb.fire(API, "11_put_restore", "PUT", f"{BASE}/{RID}", body=BODY, space=SPACE)

        # Which response fields does PUT reject when sent back?
        for field in ("id", "enabled", "created_by", "created_at", "updated_by", "updated_at", "version"):
            if field not in cur:
                print(f"  (response has no {field})")
                continue
            body = dict(BODY, **{field: cur[field]})
            kb.fire(API, f"12_put_with_response_field_{field}", "PUT", f"{BASE}/{RID}", body=body, space=SPACE,
                    note=f"Round-trip the server field '{field}' in PUT", limit=600)
        meta = dict(BODY["metadata"], version=cur.get("metadata", {}).get("version"))
        kb.fire(API, "12_put_with_metadata_version", "PUT", f"{BASE}/{RID}", body=dict(BODY, metadata=meta), space=SPACE,
                note="Round-trip metadata.version", limit=600)
        meta = dict(BODY["metadata"], owner="someone-else")
        kb.fire(API, "12_put_with_metadata_owner", "PUT", f"{BASE}/{RID}", body=dict(BODY, metadata=meta), space=SPACE,
                note="metadata.owner set by the caller", limit=600)
        kb.fire(API, "12_put_restore_after_owner", "PUT", f"{BASE}/{RID}", body=BODY, space=SPACE, limit=300)
        st, full = kb.call("GET", f"{BASE}/{RID}", space=SPACE)[:2]
        kb.fire(API, "13_put_full_get_response", "PUT", f"{BASE}/{RID}", body=full, space=SPACE,
                note="The complete GET response sent back as the PUT body", limit=800)

        # Optimistic concurrency: stale version.
        if cur.get("version"):
            kb.fire(API, "14_put_stale_version", "PUT", f"{BASE}/{RID}", body=dict(BODY, version="WzEsMV0="), space=SPACE,
                    note="Deliberately stale version string", limit=600)

        kb.fire(API, "15_patch_tags", "PATCH", f"{BASE}/{RID}",
                body={"metadata": {"tags": [TAG, "probe", "patched"]}}, space=SPACE, limit=800)
        kb.fire(API, "15b_put_restore", "PUT", f"{BASE}/{RID}", body=BODY, space=SPACE, limit=300)

        # Space awareness.
        kb.fire(API, "16_get_from_default_space", "GET", f"{BASE}/{RID}", space="default",
                note="The rule was created in gitops-dev; read it from the default space")
        field_names_only("17_list_gitops_dev_after_create", SPACE)
        _, _, default_ids = field_names_only("17b_list_default_after_create", "default")
        print("probe rule visible in default-space list:", RID in default_ids)

        # Enable / disable.
        kb.fire(API, "18_disable", "POST", f"{BASE}/{RID}/_disable", space=SPACE, limit=800)
        st, g = kb.call("GET", f"{BASE}/{RID}", space=SPACE)[:2]
        print("  enabled after _disable:", g.get("enabled"))
        kb.fire(API, "19_disable_again", "POST", f"{BASE}/{RID}/_disable", space=SPACE, limit=600)
        st, p = kb.fire(API, "20_put_while_disabled", "PUT", f"{BASE}/{RID}", body=BODY, space=SPACE, limit=400)
        print("  enabled after PUT while disabled:", p.get("enabled") if isinstance(p, dict) else p)
        kb.fire(API, "21_enable", "POST", f"{BASE}/{RID}/_enable", space=SPACE, limit=800)
        st, g = kb.call("GET", f"{BASE}/{RID}", space=SPACE)[:2]
        print("  enabled after _enable:", g.get("enabled"))

        kb.fire(API, "22_run", "POST", f"{BASE}/{RID}/_run", space=SPACE)
        kb.fire(API, "22b_run_missing", "POST", f"{BASE}/gitops-probe-api-missing/_run", space=SPACE)
        kb.fire(API, "22c_run_from_default_space", "POST", f"{BASE}/{RID}/_run", space="default")

        kb.fire(API, "23_post_create_without_id", "POST", BASE, body={**BODY, "metadata": dict(BODY["metadata"], name="gitops-probe-api post")},
                space=SPACE, note="POST create: does the server generate the id?", limit=600)
    finally:
        # Remove any rule the POST created (server-generated id) plus the probe rule.
        st, body, _, _ = kb.call("GET", f"{BASE}?per_page=100", space=SPACE)
        for item in (body or {}).get("items", []) if isinstance(body, dict) else []:
            name = item.get("metadata", {}).get("name", "")
            if name.startswith("gitops-probe-api") and item.get("id") != RID:
                s = kb.call("DELETE", f"{BASE}/{item['id']}", space=SPACE)[0]
                print("cleanup POST-created rule:", s)
        kb.fire(API, "90_delete", "DELETE", f"{BASE}/{RID}", space=SPACE)
        kb.fire(API, "91_get_after_delete", "GET", f"{BASE}/{RID}", space=SPACE)
        kb.fire(API, "92_delete_again", "DELETE", f"{BASE}/{RID}", space=SPACE)


if __name__ == "__main__":
    main()
