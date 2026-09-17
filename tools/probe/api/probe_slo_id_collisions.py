"""Phase 0 probe E2: SLO IDs are unique across ALL spaces (Kibana create_slo.ts assertSLOInexistant
searches namespaces ['*']). Check read-only that the planned demo SLO IDs are not already taken in the
shared dev project. Prints booleans and counts only.

    python3 scripts/with_env.py dev -- python3 tools/probe/api/probe_slo_id_collisions.py
"""
import kb

PLANNED = [f"svc-{svc}-{kind}" for svc in ("grid-dispatch", "turbine-telemetry") for kind in ("availability", "latency")]

st, body = kb.call("GET", "/api/observability/slos?perPage=1000&page=1")[:2]
ids = {s["id"] for s in (body or {}).get("results", [])} if isinstance(body, dict) else set()
result = {
    "http": st,
    "default_space_slo_count": len(ids),
    "default_space_ids_with_svc_prefix": len([i for i in ids if i.startswith("svc-")]),
    "default_space_ids_with_gitops_prefix": len([i for i in ids if i.startswith("gitops")]),
    "planned_ids_taken": {pid: pid in ids for pid in PLANNED},
}
for pid in PLANNED:
    result["planned_ids_taken"][pid] = result["planned_ids_taken"][pid] or kb.call("GET", f"/api/observability/slos/{pid}")[0] == 200
# Every space (read-only listing), because the uniqueness check spans all of them.
st_sp, spaces = kb.call("GET", "/api/spaces/space")[:2]
per_space = {}
for sp in [x["id"] for x in spaces] if isinstance(spaces, list) else []:
    s2, b2 = kb.call("GET", "/api/observability/slos?perPage=1000&page=1", space=sp)[:2]
    sids = {x["id"] for x in (b2 or {}).get("results", [])} if isinstance(b2, dict) else set()
    per_space[sp] = {"http": s2, "count": len(sids), "planned_taken": sorted(set(PLANNED) & sids)}
result["spaces_checked"] = len(per_space)
result["slo_count_all_spaces"] = sum(v["count"] for v in per_space.values())
result["planned_ids_taken_any_space"] = sorted({pid for v in per_space.values() for pid in v["planned_taken"]})
kb.save("space_awareness", "slo_id_collisions", "GET", "/api/observability/slos (default space)", st, result,
        note="SLO ids must be unique across every space of a project; counts and booleans only")
print(result)
