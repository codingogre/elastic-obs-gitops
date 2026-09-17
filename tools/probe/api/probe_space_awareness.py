"""Phase 0 probe E (Q8): which APIs are space-aware in the shared dev project.

Read-only for everything that already exists: only counts are recorded, never IDs or names of
other demos' objects. Creates one Agent Builder ES|QL tool, gitops-probe-api-tool, in gitops-dev
and deletes it at the end.

    python3 scripts/with_env.py dev -- python3 tools/probe/api/probe_space_awareness.py
"""
import json

import kb

A = "space_awareness"
SPACE = "gitops-dev"
TOOL = "gitops-probe-api-tool"


def ids_of(kind, space):
    """Return (status, set of ids, extra) for one listing in one space."""
    if kind == "workflows":
        st, b = kb.call("GET", "/api/workflows?size=500&page=1", space=space)[:2]
        items = (b or {}).get("results") or (b or {}).get("data") or (b or {}).get("items") or [] if isinstance(b, dict) else []
        return st, {i.get("id") for i in items}, {"top_keys": sorted(b.keys()) if isinstance(b, dict) else None}
    if kind == "agent_builder_tools":
        st, b = kb.call("GET", "/api/agent_builder/tools", space=space)[:2]
        items = (b or {}).get("results", []) if isinstance(b, dict) else []
        custom = {i["id"] for i in items if not i.get("readonly")}
        return st, custom, {"builtin_readonly": sum(1 for i in items if i.get("readonly")), "custom": len(custom)}
    if kind == "agent_builder_agents":
        st, b = kb.call("GET", "/api/agent_builder/agents", space=space)[:2]
        items = (b or {}).get("results", []) if isinstance(b, dict) else []
        custom = {i["id"] for i in items if not i.get("readonly")}
        return st, custom, {"builtin_readonly": sum(1 for i in items if i.get("readonly")), "custom": len(custom)}
    if kind == "agent_builder_skills":
        st, b = kb.call("GET", "/api/agent_builder/skills", space=space)[:2]
        items = (b or {}).get("results", []) if isinstance(b, dict) else []
        custom = {i["id"] for i in items if not i.get("readonly")}
        return st, custom, {"builtin_readonly": sum(1 for i in items if i.get("readonly")), "custom": len(custom)}
    if kind == "alerting_v2_rules":
        st, b = kb.call("GET", "/api/alerting/v2/rules?per_page=100", space=space)[:2]
        return st, {i["id"] for i in (b or {}).get("items", [])} if isinstance(b, dict) else set(), {}
    if kind == "alerting_v2_action_policies":
        st, b = kb.call("GET", "/api/alerting/v2/action_policies?per_page=100", space=space)[:2]
        return st, {i["id"] for i in (b or {}).get("items", [])} if isinstance(b, dict) else set(), {}
    if kind == "slos":
        st, b = kb.call("GET", "/api/observability/slos?perPage=1000&page=1", space=space)[:2]
        items = (b or {}).get("results", []) if isinstance(b, dict) else []
        return st, {i["id"] for i in items}, {"total": (b or {}).get("total") if isinstance(b, dict) else None}
    if kind == "connectors":
        st, b = kb.call("GET", "/api/actions/connectors", space=space)[:2]
        items = b if isinstance(b, list) else []
        pre = {i["id"] for i in items if i.get("is_preconfigured")}
        user = {i["id"] for i in items if not i.get("is_preconfigured")}
        return st, user, {"preconfigured": len(pre), "user_created": len(user)}
    if kind == "classic_rules":
        st, b = kb.call("GET", "/api/alerting/rules/_find?per_page=1000", space=space)[:2]
        return st, {i["id"] for i in (b or {}).get("data", [])} if isinstance(b, dict) else set(), {}
    if kind == "dashboards":
        st, b = kb.call("GET", "/api/dashboards?per_page=1000", space=space)[:2]
        return st, {i["id"] for i in (b or {}).get("data", [])} if isinstance(b, dict) else set(), {}
    raise ValueError(kind)


KINDS = ["workflows", "agent_builder_tools", "agent_builder_agents", "agent_builder_skills", "alerting_v2_rules",
         "alerting_v2_action_policies", "slos", "connectors", "classic_rules", "dashboards"]


def main():
    summary = {}
    for kind in KINDS:
        st_d, ids_d, ex_d = ids_of(kind, "default")
        st_g, ids_g, ex_g = ids_of(kind, SPACE)
        shared = ids_d & ids_g
        row = {
            "http_default": st_d, "http_gitops_dev": st_g,
            "count_default_space": len(ids_d), "count_gitops_dev": len(ids_g),
            "default_objects_visible_in_gitops_dev": len(shared),
            "gitops_dev_objects_visible_in_default": len(ids_g & ids_d),
            "extra_default": ex_d, "extra_gitops_dev": ex_g,
        }
        # Built-in (Elastic-provided) objects may show up in every space; name only those.
        row["overlap_elastic_builtin_ids"] = sorted(i for i in shared if str(i).startswith(("elastic-", ".")))
        row["overlap_other_count"] = len([i for i in shared if not str(i).startswith(("elastic-", "."))])
        summary[kind] = row
        print(f"{kind:30s} default={st_d}/{len(ids_d):3d} gitops-dev={st_g}/{len(ids_g):3d} overlap={len(shared)} {ex_d} {ex_g}")

    # Create one tool in gitops-dev and look for it from the default space.
    body = {"id": TOOL, "type": "esql", "description": "Temporary probe object. Safe to delete.", "tags": ["gitops-probe-api"],
            "configuration": {"query": 'FROM traces-* | WHERE service.name == "grid-dispatch" | STATS spans = COUNT(*)', "params": {}}}
    try:
        kb.fire(A, "tool_01_create_gitops_dev", "POST", "/api/agent_builder/tools", body=body, space=SPACE, limit=600)
        kb.fire(A, "tool_02_get_gitops_dev", "GET", f"/api/agent_builder/tools/{TOOL}", space=SPACE, limit=600)
        kb.fire(A, "tool_03_get_default_space", "GET", f"/api/agent_builder/tools/{TOOL}", space="default", limit=400)
        st, ids, _ = ids_of("agent_builder_tools", "default")
        print("probe tool in default-space list:", TOOL in ids)
        summary["agent_builder_tools"]["probe_tool_created_in_gitops_dev_visible_in_default"] = TOOL in ids
    finally:
        kb.fire(A, "tool_90_delete", "DELETE", f"/api/agent_builder/tools/{TOOL}", space=SPACE, limit=300)
        kb.fire(A, "tool_91_get_after_delete", "GET", f"/api/agent_builder/tools/{TOOL}", space=SPACE, limit=300)

    kb.save(A, "summary_counts", "GET", "(several list endpoints, default vs gitops-dev)", 200, summary,
            note="Counts only. overlap = objects returned by both spaces' listings.")
    print(json.dumps(summary, indent=1)[:4000])


if __name__ == "__main__":
    main()
