"""Verify that no gitops-probe-api* object is left in dev (gitops-dev space and the ES level). Read-only.

    python3 scripts/with_env.py dev -- python3 tools/probe/api/verify_cleanup.py
"""
import kb

SPACE = "gitops-dev"
P = "gitops-probe-api"
left = {}


def check(name, status, ids):
    mine = sorted(i for i in ids if str(i).startswith(P))
    left[name] = mine
    print(f"{name:34s} HTTP {status}  leftovers: {mine}")


st, b = kb.call("GET", "/api/alerting/v2/rules?per_page=100", space=SPACE)[:2]
check("alerting v2 rules", st, [i["id"] for i in b.get("items", [])] + [i["metadata"]["name"] for i in b.get("items", [])])
st, b = kb.call("GET", "/api/alerting/v2/action_policies?per_page=100", space=SPACE)[:2]
check("alerting v2 action policies", st, [i["id"] for i in b.get("items", [])])
st, b = kb.call("GET", "/api/workflows?size=500&page=1", space=SPACE)[:2]
check("workflows", st, [i["id"] for i in b.get("results", [])])
for wid in ("gitops-probe-api-wf", "gitops-probe-api-wf2"):
    print(f"  GET workflow {wid}: {kb.call('GET', f'/api/workflows/workflow/{wid}', space=SPACE)[0]}")
st, b = kb.call("GET", "/api/dashboards?per_page=1000", space=SPACE)[:2]
check("dashboards", st, [i["id"] for i in b.get("data", [])] + [i["data"].get("title", "") for i in b.get("data", [])])
st, b = kb.call("GET", "/api/agent_builder/tools", space=SPACE)[:2]
check("agent builder tools", st, [i["id"] for i in b.get("results", [])])
st, b = kb.call("GET", "/api/agent_builder/conversations", space=SPACE)[:2]
convs = b.get("results", []) if isinstance(b, dict) else []
check("agent builder conversations", st, [c.get("title", "") for c in convs if "pong" in c.get("title", "").lower()] and ["gitops-probe-api-conversation"] or [])
st, b = kb.call("GET", "/api/alerting/rules/_find?per_page=1000", space=SPACE)[:2]
check("classic rules", st, [i["id"] for i in b.get("data", [])])
st, b = kb.call("GET", "/internal/kibana/settings", space=SPACE, internal=True)[:2]
keys = list((b or {}).get("settings", {}).keys())
check("space settings keys", st, [k for k in keys if k.startswith(P)] + ([P + ":dateFormat:dow"] if "dateFormat:dow" in keys else [])
      + ([P + ":alerting:v2:enabled(space copy)"] if "alerting:v2:enabled" in keys else []))
st, b, _ = kb.es_call("GET", f"/_resolve/index/{P}*")
check("ES indices / data streams", st, [i["name"] for i in (b or {}).get("indices", [])] + [d["name"] for d in (b or {}).get("data_streams", [])])
st, g = kb.call("GET", "/internal/kibana/global_settings", internal=True)[:2]
print("global alerting:v2:enabled:", (g or {}).get("settings", {}).get("alerting:v2:enabled"))
print("ALL CLEAN" if not any(left.values()) else "LEFTOVERS FOUND")
