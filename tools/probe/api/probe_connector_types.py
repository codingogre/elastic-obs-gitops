"""Phase 0 probe F (Q2): can a classic rule action run a workflow? Read-only.

Lists connector types and system connectors in gitops-dev and records anything workflow-related.

    python3 scripts/with_env.py dev -- python3 tools/probe/api/probe_connector_types.py
"""
import json

import kb

A = "connector_types"
SPACE = "gitops-dev"


def main():
    st, types, el, _ = kb.call("GET", "/api/actions/connector_types", space=SPACE)
    print("connector_types HTTP", st, "count", len(types) if isinstance(types, list) else types)
    wf = [t for t in types if "workflow" in (t.get("id", "") + t.get("name", "")).lower()] if isinstance(types, list) else []
    system = [t for t in types if t.get("is_system_action_type")] if isinstance(types, list) else []
    kb.save(A, "01_connector_types_workflow_related", "GET", "/api/actions/connector_types", st,
            {"total_types": len(types) if isinstance(types, list) else None,
             "workflow_related": wf,
             "system_action_types": [{k: t.get(k) for k in ("id", "name", "enabled", "enabled_in_config", "enabled_in_license",
                                                            "minimum_license_required", "supported_feature_ids", "is_system_action_type")}
                                     for t in system],
             "all_type_ids": sorted(t.get("id") for t in types) if isinstance(types, list) else None},
            space=SPACE, elapsed=el)
    print("workflow-related types:", json.dumps(wf, indent=1))
    print("system action types:", [t.get("id") for t in system])

    st, conns, el, _ = kb.call("GET", "/api/actions/connectors", space=SPACE)
    sys_conns = [c for c in conns if c.get("is_system_action")] if isinstance(conns, list) else []
    wf_conns = [c for c in conns if "workflow" in (c.get("connector_type_id", "") + c.get("id", "")).lower()] if isinstance(conns, list) else []
    kb.save(A, "02_system_connectors", "GET", "/api/actions/connectors", st,
            {"system_action_connectors": sys_conns, "workflow_related_connectors": wf_conns}, space=SPACE, elapsed=el,
            note="Preconfigured system connectors are the same in every space")
    print("system connectors:", json.dumps(sys_conns, indent=1)[:2000])
    print("workflow connectors:", json.dumps(wf_conns, indent=1)[:1000])

    # System action types/connectors are hidden from the public listings; the internal routes include them.
    st, itypes, el, _ = kb.call("GET", "/internal/actions/connector_types", space=SPACE, internal=True)
    iwf = [t for t in itypes if "workflow" in (t.get("id", "") + t.get("name", "")).lower()] if isinstance(itypes, list) else itypes
    kb.save(A, "03_internal_connector_types_workflows", "GET", "/internal/actions/connector_types", st,
            {"total_types_internal": len(itypes) if isinstance(itypes, list) else None,
             "types_only_in_internal_listing": sorted({t.get("id") for t in itypes} - {t.get("id") for t in types})
             if isinstance(itypes, list) and isinstance(types, list) else None,
             "workflow_related": iwf}, space=SPACE, elapsed=el)
    print("internal connector_types HTTP", st, "workflow-related:", json.dumps(iwf, indent=1)[:1500])
    st, iconns, el, _ = kb.call("GET", "/internal/actions/connectors", space=SPACE, internal=True)
    isys = [c for c in iconns if c.get("is_system_action")] if isinstance(iconns, list) else iconns
    kb.save(A, "04_internal_system_connectors", "GET", "/internal/actions/connectors", st,
            {"system_action_connectors": isys}, space=SPACE, elapsed=el)
    print("internal system connectors HTTP", st, json.dumps(isys, indent=1)[:2500])

    # Which rule types accept system actions / workflows? (rule types list, read-only)
    st, rtypes, el, _ = kb.call("GET", "/api/alerting/rule_types", space=SPACE)
    if isinstance(rtypes, list):
        es = [r for r in rtypes if r.get("id") in (".es-query", "slo.rules.burnRate", "observability.rules.custom_threshold")]
        print("rule types sample:", [(r.get("id"), r.get("has_alerts_mappings"), r.get("producer")) for r in es])


if __name__ == "__main__":
    main()
