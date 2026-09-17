"""Phase 0 probe G: Agent Builder converse API shape and latency (dev, gitops-dev only).

Lists agents in gitops-dev, calls the built-in default agent once with a trivial input, records the
response shape and latency, then deletes the conversation it created.

    python3 scripts/with_env.py dev -- python3 tools/probe/api/probe_converse.py
"""
import json

import kb

A = "agent_builder_converse"
SPACE = "gitops-dev"


def main():
    st, agents, el, _ = kb.call("GET", "/api/agent_builder/agents", space=SPACE)
    items = (agents or {}).get("results", []) if isinstance(agents, dict) else []
    builtin = [a for a in items if a.get("id") == "elastic-ai-agent"]
    kb.save(A, "01_list_agents_gitops_dev", "GET", "/api/agent_builder/agents", st,
            {"top_level_keys": sorted(agents.keys()) if isinstance(agents, dict) else None,
             "agent_count": len(items), "agent_field_names": sorted({k for a in items for k in a.keys()}),
             "builtin_default_agent": builtin},
            space=SPACE, elapsed=el, note="Only the built-in default agent is recorded in full")
    print("agents in gitops-dev:", [a.get("id") for a in items if a.get("id", "").startswith(("elastic-", "gitops-"))],
          "total", len(items))
    if not builtin:
        raise SystemExit("elastic-ai-agent not listed in gitops-dev")

    body = {"agent_id": "elastic-ai-agent", "input": "Reply with exactly one word: pong. Do not call any tools."}
    st, resp, el, _ = kb.call("POST", "/api/agent_builder/converse", body=body, space=SPACE, timeout=300)
    kb.save(A, "02_converse_default_agent", "POST", "/api/agent_builder/converse", st, resp, request=body, space=SPACE, elapsed=el)
    print(f"converse HTTP {st} in {el}s")
    if isinstance(resp, dict):
        print("top-level keys:", list(resp.keys()))
        print("response keys:", list((resp.get("response") or {}).keys()))
        print("final text (response.message):", json.dumps((resp.get("response") or {}).get("message"))[:300])
        print("steps:", [s.get("type") for s in resp.get("steps", [])])
        extra = {k: v for k, v in resp.items() if k not in ("steps", "response")}
        print("other fields:", json.dumps(kb.sanitize(extra))[:800])
        cid = resp.get("conversation_id")
        if cid:
            kb.fire(A, "03_get_conversation", "GET", f"/api/agent_builder/conversations/{cid}", space=SPACE, limit=1500)
            kb.fire(A, "04_delete_conversation", "DELETE", f"/api/agent_builder/conversations/{cid}", space=SPACE, limit=300)
            kb.fire(A, "05_get_conversation_after_delete", "GET", f"/api/agent_builder/conversations/{cid}", space=SPACE, limit=300)
    else:
        print(str(resp)[:1000])


if __name__ == "__main__":
    main()
