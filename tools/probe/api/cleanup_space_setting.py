"""Remove a stray key from the gitops-dev SPACE settings (config saved object in that space only).

probe_settings.py step dev_14 showed that the space route accepts a global-scope key and stores it
in the space's own config object. This removes that copy through the same space route and proves
that the global value is untouched.

    python3 scripts/with_env.py dev -- python3 tools/probe/api/cleanup_space_setting.py
"""
import kb

SPACE = "gitops-dev"
KEY = "alerting:v2:enabled"

st, g = kb.call("GET", "/internal/kibana/global_settings", internal=True)[:2]
before_global = (g or {}).get("settings", {}).get(KEY)
print("global before:", st, before_global)
st, s = kb.call("GET", "/internal/kibana/settings", space=SPACE, internal=True)[:2]
print("space before:", st, (s or {}).get("settings", {}).get(KEY))

kb.fire("kibana_settings", "dev_16_delete_global_key_from_space_config", "DELETE", f"/internal/kibana/settings/{KEY}",
        space=SPACE, internal=True, note="Removes the space-level copy written by dev_14; the global value must stay unchanged", limit=600)

st, s = kb.call("GET", "/internal/kibana/settings", space=SPACE, internal=True)[:2]
print("space after:", st, (s or {}).get("settings", {}).get(KEY, "<absent>"), sorted((s or {}).get("settings", {}).keys()))
st, g = kb.call("GET", "/internal/kibana/global_settings", internal=True)[:2]
after_global = (g or {}).get("settings", {}).get(KEY)
print("global after:", st, after_global, "UNCHANGED" if after_global == before_global else "CHANGED")
st, d = kb.call("GET", "/internal/kibana/settings", space="default", internal=True)[:2]
print("default space has key:", KEY in (d or {}).get("settings", {}))
