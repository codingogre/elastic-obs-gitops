"""Phase 0 probe C: Dashboards API shapes (dev, gitops-dev only).

Creates gitops-probe-api-dashboard (+ a write_restricted and a UUID-keyed variant, + one POST-created
dashboard) in gitops-dev and deletes all of them at the end.

    python3 scripts/with_env.py dev -- python3 tools/probe/api/probe_dashboards.py
"""
import copy
import json
import time

import kb

A = "dashboards"
SPACE = "gitops-dev"
DID = "gitops-probe-api-dashboard"
RID = "gitops-probe-api-dashboard-restricted"
UID = "5f0c7a52-3b8e-4f2e-9a61-0d7c1e2b9a01"  # fixed UUID v4 for the probe
BASE = "/api/dashboards"
TITLE = "gitops-probe-api dashboard (Phase 0 API probe)"

BODY = {
    "title": TITLE,
    "description": "Temporary probe object. Safe to delete.",
    "time_range": {"from": "now-1h", "to": "now"},
    "panels": [
        {
            "type": "markdown",
            "id": "probe-notes",
            "grid": {"x": 0, "y": 0, "w": 24, "h": 6},
            "config": {"content": "## Probe\nTemporary markdown panel.", "settings": {"open_links_in_new_tab": True}},
        },
        {
            "type": "vis",
            "id": "probe-span-count",
            "grid": {"x": 24, "y": 0, "w": 24, "h": 6},
            "config": {
                "title": "Spans (grid-dispatch)",
                "type": "metric",
                "data_source": {
                    "type": "esql",
                    "query": 'FROM traces-* | WHERE service.name == "grid-dispatch" | STATS spans = COUNT(*)',
                },
                "metrics": [{"type": "primary", "column": "spans"}],
            },
        },
    ],
}

INTERESTING_HEADERS = ("elastic-api-version", "content-type", "location", "etag", "warning", "kbn-name")


def headers_of(method, path, body=None, space=SPACE):
    st, resp, el, h = kb.call(method, path, body=body, space=space)
    picked = {k.lower(): v for k, v in h.items() if k.lower() in INTERESTING_HEADERS}
    return st, resp, picked


def diff(a, b, prefix=""):
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in list(a.keys()) + [k for k in b.keys() if k not in a]:
            p = f"{prefix}.{k}" if prefix else k
            if k not in b:
                out.append(f"  - {p} (sent, not returned)")
            elif k not in a:
                out.append(f"  + {p} = {json.dumps(kb.sanitize({k: b[k]})[k])[:200]}")
            else:
                out += diff(a[k], b[k], p)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append(f"  ~ {prefix}: list length {len(a)} -> {len(b)}")
        for i, (x, y) in enumerate(zip(a, b)):
            out += diff(x, y, f"{prefix}[{i}]")
    elif a != b:
        out.append(f"  ~ {prefix}: sent {json.dumps(a)[:120]} got {json.dumps(kb.sanitize(b))[:120]}")
    return out


def main():
    post_id = None
    try:
        kb.fire(A, "00_get_missing", "GET", f"{BASE}/{DID}", space=SPACE)
        st, created = kb.fire(A, "01_put_create", "PUT", f"{BASE}/{DID}", body=BODY, space=SPACE,
                              note="Create (upsert) with a caller-chosen slug id; one markdown + one ES|QL metric panel",
                              limit=3000)
        if st not in (200, 201):
            raise SystemExit("dashboard create failed")
        st, got, hdr = headers_of("GET", f"{BASE}/{DID}")
        kb.save(A, "02_get", "GET", f"{BASE}/{DID}", st, got, space=SPACE, note={"response_headers": hdr})
        print("GET headers:", hdr)
        print("top-level keys:", list(got.keys()), "data keys:", list(got.get("data", {}).keys()))
        print("diff request -> GET.data:")
        print("\n".join(diff(BODY, got.get("data", {}))))
        print("meta:", json.dumps(kb.sanitize(got.get("meta"))))

        time.sleep(1.2)
        st, same = kb.fire(A, "03_put_identical", "PUT", f"{BASE}/{DID}", body=BODY, space=SPACE,
                           note="Identical body: does meta.version / updated_at change?", limit=300)
        print("  no-op PUT meta before:", json.dumps(kb.sanitize(got.get("meta"))))
        print("  no-op PUT meta after :", json.dumps(kb.sanitize(same.get("meta"))) if isinstance(same, dict) else same)

        st, cur = kb.call("GET", f"{BASE}/{DID}", space=SPACE)[:2]
        kb.fire(A, "04_put_roundtrip_get_data", "PUT", f"{BASE}/{DID}", body=cur["data"], space=SPACE,
                note="GET response .data sent back unchanged as the PUT body", limit=300)
        kb.fire(A, "05_put_full_get_response", "PUT", f"{BASE}/{DID}", body=cur, space=SPACE,
                note="Whole GET response (id, data, meta) as the PUT body", limit=500)
        kb.fire(A, "05b_put_with_version_in_body", "PUT", f"{BASE}/{DID}", body=dict(BODY, version=cur["meta"].get("version")),
                space=SPACE, note="meta.version as a top-level body field", limit=500)

        upd = copy.deepcopy(BODY)
        upd["title"] = TITLE + " v2"
        upd["panels"] = [upd["panels"][1]]
        kb.fire(A, "06_put_update_title_drop_panel", "PUT", f"{BASE}/{DID}", body=upd, space=SPACE,
                note="Full replacement: title changed, markdown panel removed", limit=400)
        st, g = kb.fire(A, "07_get_after_update", "GET", f"{BASE}/{DID}", space=SPACE, limit=400)
        print("  panels after update:", [p.get("id") for p in g.get("data", {}).get("panels", [])])

        bad = copy.deepcopy(BODY)
        bad["panels"].append({"type": "not_a_panel_type", "id": "bad", "grid": {"x": 0, "y": 6, "w": 12, "h": 4}, "config": {}})
        kb.fire(A, "08_put_invalid_panel_type", "PUT", f"{BASE}/{DID}", body=bad, space=SPACE,
                note="Unknown panel type", limit=1500)
        bad2 = copy.deepcopy(BODY)
        bad2["panels"][1]["config"]["metrics"] = [{"type": "primary", "column": "no_such_column"}]
        kb.fire(A, "09_put_esql_column_mismatch", "PUT", f"{BASE}/{DID}", body=bad2, space=SPACE,
                note="ES|QL metric column not produced by the query", limit=800)
        bad3 = copy.deepcopy(BODY)
        bad3["unknown_top_level"] = True
        kb.fire(A, "10_put_unknown_top_level_key", "PUT", f"{BASE}/{DID}", body=bad3, space=SPACE, limit=600)
        kb.fire(A, "10b_put_restore", "PUT", f"{BASE}/{DID}", body=BODY, space=SPACE, limit=200)

        # Space awareness.
        kb.fire(A, "11_get_from_default_space", "GET", f"{BASE}/{DID}", space="default", limit=400)

        # POST create (server-generated id), and POST with an id in the body.
        st, p = kb.fire(A, "12_post_create", "POST", BASE, body=dict(BODY, title=TITLE + " (POST)"), space=SPACE,
                        note="POST create: server generates the id", limit=500)
        if st in (200, 201) and isinstance(p, dict):
            post_id = p.get("id")
        st, p2 = kb.fire(A, "13_post_with_id_in_body", "POST", BASE, body=dict(BODY, id="gitops-probe-api-post-id", title=TITLE + " (POST id)"),
                         space=SPACE, note="POST with id in the body", limit=500)
        if st in (200, 201) and isinstance(p2, dict):
            kb.call("DELETE", f"{BASE}/{p2.get('id')}", space=SPACE)

        # UUID id.
        kb.fire(A, "14_put_create_uuid_id", "PUT", f"{BASE}/{UID}", body=dict(BODY, title=TITLE + " (uuid)"), space=SPACE, limit=300)

        # access_control on create.
        st, r = kb.fire(A, "15_put_create_write_restricted", "PUT", f"{BASE}/{RID}",
                        body=dict(BODY, title=TITLE + " (restricted)", access_control={"access_mode": "write_restricted"}),
                        space=SPACE, note="access_control.access_mode=write_restricted on create", limit=2500)
        kb.fire(A, "16_get_write_restricted", "GET", f"{BASE}/{RID}", space=SPACE, limit=2500)
        kb.fire(A, "17_put_update_restricted_same_key", "PUT", f"{BASE}/{RID}",
                body=dict(BODY, title=TITLE + " (restricted v2)", access_control={"access_mode": "write_restricted"}),
                space=SPACE, note="Owner (same API key) updates a write_restricted dashboard", limit=600)
        kb.fire(A, "18_put_restricted_without_access_control", "PUT", f"{BASE}/{RID}",
                body=dict(BODY, title=TITLE + " (restricted v3)"),
                space=SPACE, note="access_control omitted on update: is the mode kept or reset?", limit=2500)
        st, g = kb.call("GET", f"{BASE}/{RID}", space=SPACE)[:2]
        print("  access_control after PUT without it:", json.dumps((g.get("data") or {}).get("access_control")))
        kb.fire(A, "19_put_restricted_to_default", "PUT", f"{BASE}/{RID}",
                body=dict(BODY, title=TITLE + " (restricted v4)", access_control={"access_mode": "default"}),
                space=SPACE, note="Switch access_mode back to default", limit=2500)

        st, lst = kb.call("GET", f"{BASE}?query=gitops-probe-api&per_page=20", space=SPACE)[:2]
        kb.save(A, "20_list_search", "GET", f"{BASE}?query=gitops-probe-api&per_page=20", st, lst, space=SPACE)
        print("list keys:", list(lst.keys()) if isinstance(lst, dict) else lst)
    finally:
        print("\n===== Cleanup =====")
        for i, did in enumerate([DID, RID, UID] + ([post_id] if post_id else [])):
            st, resp = kb.fire(A, f"9{i}_delete_{'post' if did == post_id else did.split('-')[-1]}", "DELETE", f"{BASE}/{did}", space=SPACE, limit=300)
            print("   GET after delete:", kb.call("GET", f"{BASE}/{did}", space=SPACE)[0])
        kb.fire(A, "99_delete_again", "DELETE", f"{BASE}/{DID}", space=SPACE, limit=300)
        st, lst = kb.call("GET", f"{BASE}?query=gitops-probe-api&per_page=50", space=SPACE)[:2]
        left = [d.get("id") for d in (lst or {}).get("dashboards", lst.get("items", []) if isinstance(lst, dict) else [])] if isinstance(lst, dict) else lst
        print("remaining gitops-probe-api dashboards (search):", left)


if __name__ == "__main__":
    main()
