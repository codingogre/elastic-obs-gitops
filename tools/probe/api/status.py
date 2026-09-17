"""Print the Kibana version and build flavor of the current environment (read-only)."""
import kb

status, body, elapsed, _ = kb.call("GET", "/api/status")
v = (body or {}).get("version", {}) if isinstance(body, dict) else {}
print("HTTP", status, "version", v.get("number"), "flavor", v.get("build_flavor"),
      "build_date", v.get("build_date"), "sha", (v.get("build_hash") or "")[:8], f"{elapsed}s")
print("identity strings to scrub:", len(kb.identity_strings()))
