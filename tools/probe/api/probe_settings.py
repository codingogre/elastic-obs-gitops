"""Phase 0 probe D (Q11): Kibana advanced settings API on Serverless.

    python3 scripts/with_env.py dev  -- python3 tools/probe/api/probe_settings.py dev
    python3 scripts/with_env.py prod -- python3 tools/probe/api/probe_settings.py prod   # GETs only

Global settings are READ ONLY in both environments. The only write is a space-scoped setting
(dateFormat:dow) in dev space gitops-dev, which is restored to its previous state at the end.
"""
import sys

import kb

A = "kibana_settings"
KEY = "alerting:v2:enabled"
SPACE = "gitops-dev"
DOW = "dateFormat:dow"


def only(settings_body, keys):
    s = (settings_body or {}).get("settings", {}) if isinstance(settings_body, dict) else {}
    return {"settings": {k: s[k] for k in keys if k in s}, "all_setting_keys": sorted(s.keys())}


def read_global(env):
    st, body, el, h = kb.call("GET", "/internal/kibana/global_settings", internal=True)
    kb.save(A, f"{env}_01_get_internal_global_settings", "GET", "/internal/kibana/global_settings", st,
            only(body, [KEY]) if st == 200 else body, elapsed=el,
            note={"headers_sent": ["kbn-xsrf", "Authorization: ApiKey", "x-elastic-internal-origin: Kibana"],
                  "response_elastic_api_version": h.get("elastic-api-version"),
                  "recorded": f"only {KEY} plus the list of global keys that have a user value"})
    val = (body or {}).get("settings", {}).get(KEY) if isinstance(body, dict) else None
    print(f"[{env}] GET /internal/kibana/global_settings: HTTP {st} {KEY} = {val}")
    return st, val


def prod():
    read_global("prod")


def dev():
    # Public routes (not registered on serverless: uiSettings.publicApiEnabled=false).
    for path in ("/api/kibana/settings", "/api/kibana/global_settings"):
        st, body, el, _ = kb.call("GET", path)
        kb.save(A, "dev_00_get_public" + path.replace("/", "_"), "GET", path, st, body, elapsed=el)
        print(f"GET {path}: HTTP {st} {str(body)[:200]}")
    # Internal route without the internal-origin header.
    st, body, el, _ = kb.call("GET", "/internal/kibana/global_settings")
    kb.save(A, "dev_00_get_internal_without_origin_header", "GET", "/internal/kibana/global_settings", st, body, elapsed=el)
    print(f"GET /internal/kibana/global_settings (no x-elastic-internal-origin): HTTP {st} {str(body)[:200]}")

    read_global("dev")
    st, body, el, _ = kb.call("GET", "/internal/kibana/global_settings", space=SPACE, internal=True)
    v = (body or {}).get("settings", {}).get(KEY) if isinstance(body, dict) else None
    print(f"GET /s/{SPACE}/internal/kibana/global_settings: HTTP {st} {KEY} = {v}")

    # Is alerting:v2:enabled stored per space? (read only)
    for sp in ("default", SPACE):
        st, body, el, _ = kb.call("GET", "/internal/kibana/settings", space=sp, internal=True)
        s = (body or {}).get("settings", {}) if isinstance(body, dict) else {}
        print(f"GET space={sp} /internal/kibana/settings: HTTP {st} has {KEY}: {KEY in s}; has {DOW}: {DOW in s}; keys={sorted(s.keys())}")
        if sp == "default":
            kb.save(A, "dev_02_get_space_settings_default_space", "GET", "/internal/kibana/settings", st, only(body, [KEY, DOW]),
                    elapsed=el, note="Default space of the shared project: only the probed keys and key names are recorded")

    # Space-scoped write path, proven in gitops-dev.
    st, before, el, _ = kb.call("GET", "/internal/kibana/settings", space=SPACE, internal=True)
    kb.save(A, "dev_03_get_space_settings_before", "GET", "/internal/kibana/settings", st, before, space=SPACE, elapsed=el)
    prior = (before or {}).get("settings", {}).get(DOW, {}).get("userValue") if isinstance(before, dict) else None
    print(f"prior {DOW} user value in {SPACE}: {prior!r}")
    try:
        kb.fire(A, "dev_04_post_set_one", "POST", f"/internal/kibana/settings/{DOW}", body={"value": "Monday"},
                space=SPACE, internal=True, note="Set one space setting")
        kb.fire(A, "dev_05_get_after_set", "GET", "/internal/kibana/settings", space=SPACE, internal=True)
        st, d, _, _ = kb.call("GET", "/internal/kibana/settings", space="default", internal=True)
        print(f"  default space {DOW} after gitops-dev write: {(d or {}).get('settings', {}).get(DOW)}")
        kb.fire(A, "dev_06_post_set_one_same_value", "POST", f"/internal/kibana/settings/{DOW}", body={"value": "Monday"},
                space=SPACE, internal=True, note="Same value again (idempotent?)", limit=400)
        kb.fire(A, "dev_07_post_reset_one_null", "POST", f"/internal/kibana/settings/{DOW}", body={"value": None},
                space=SPACE, internal=True, note="value=null resets to the default")
        kb.fire(A, "dev_08_post_set_many", "POST", "/internal/kibana/settings", body={"changes": {DOW: "Monday"}},
                space=SPACE, internal=True, note="Bulk form: {changes: {key: value}}")
        kb.fire(A, "dev_09_delete_one", "DELETE", f"/internal/kibana/settings/{DOW}", space=SPACE, internal=True,
                note="DELETE also resets to the default")
        kb.fire(A, "dev_10_delete_one_again", "DELETE", f"/internal/kibana/settings/{DOW}", space=SPACE, internal=True,
                note="DELETE when no user value is set", limit=400)
        kb.fire(A, "dev_11_post_invalid_value", "POST", f"/internal/kibana/settings/{DOW}", body={"value": "Funday"},
                space=SPACE, internal=True, note="Value outside the setting's schema", limit=800)
        kb.fire(A, "dev_12_post_unknown_key", "POST", "/internal/kibana/settings/gitops-probe-api:unknown", body={"value": 1},
                space=SPACE, internal=True, note="Key that is not registered / not on the serverless allowlist", limit=800)
        kb.fire(A, "dev_13_post_set_one_without_internal_header", "POST", f"/internal/kibana/settings/{DOW}",
                body={"value": "Monday"}, space=SPACE, internal=False, note="Missing x-elastic-internal-origin", limit=400)
        kb.fire(A, "dev_14_post_set_global_key_via_space_route", "POST", f"/internal/kibana/settings/{KEY}",
                body={"value": True}, space=SPACE, internal=True,
                note="A global-scope key sent to the SPACE route. Observed: HTTP 200 and the key is stored in the "
                     "space's own config object (global value untouched). Removed again in finally.", limit=800)
    finally:
        # The space route stores whatever key it gets in the space config object; remove the copy.
        kb.call("DELETE", f"/internal/kibana/settings/{KEY}", space=SPACE, internal=True)
        if prior is None:
            kb.call("DELETE", f"/internal/kibana/settings/{DOW}", space=SPACE, internal=True)
            kb.call("DELETE", "/internal/kibana/settings/gitops-probe-api:unknown", space=SPACE, internal=True)
        else:
            kb.call("POST", f"/internal/kibana/settings/{DOW}", body={"value": prior}, space=SPACE, internal=True)
        st, after, el, _ = kb.call("GET", "/internal/kibana/settings", space=SPACE, internal=True)
        kb.save(A, "dev_15_get_space_settings_final", "GET", "/internal/kibana/settings", st, after, space=SPACE, elapsed=el)
        s = (after or {}).get("settings", {}) if isinstance(after, dict) else {}
        print(f"final {SPACE} settings keys: {sorted(s.keys())}; {DOW} = {s.get(DOW)}")
        st, g = kb.call("GET", "/internal/kibana/global_settings", internal=True)[:2]
        print(f"final global {KEY} = {(g or {}).get('settings', {}).get(KEY)}")


if __name__ == "__main__":
    {"dev": dev, "prod": prod}[sys.argv[1]]()
