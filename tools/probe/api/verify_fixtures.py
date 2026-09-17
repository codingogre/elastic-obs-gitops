"""Scan fixtures/ and api/ for anything that must not be committed. Prints file names and rule names only.

Extra forbidden words (for example customer names) come from PROBE_FORBIDDEN_TERMS (comma-separated), so
they are never written into this public repository.

    python3 scripts/with_env.py dev  -- python3 tools/probe/api/verify_fixtures.py
    python3 scripts/with_env.py prod -- python3 tools/probe/api/verify_fixtures.py
"""
import os
import re
from pathlib import Path

import kb

ROOT = Path(__file__).resolve().parent.parent
checks = {
    "api key": [kb.KEY, kb.ES_KEY],
    "kibana/es endpoint": [kb.KB, kb.ES] + [h for h in kb._hosts() if len(h) > 12],
    "identity": kb.identity_strings(),
}
TERMS = [t.strip() for t in os.environ.get("PROBE_FORBIDDEN_TERMS", "").split(",") if t.strip()]
regexes = {
    "profile uid": re.compile(r"\bu_[A-Za-z0-9_-]{20,}"),
    "email": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "cloud host": re.compile(r"\.elastic\.cloud|\.aws\.elastic|us-west-2"),
}
if TERMS:
    regexes["forbidden term"] = re.compile("|".join(r"\b" + re.escape(t) + r"\b" for t in TERMS), re.I)
bad = 0
for f in sorted(list((ROOT / "fixtures").rglob("*.json")) + list((ROOT / "api").glob("*.py"))):
    text = f.read_text(errors="replace")
    hits = [name for name, vals in checks.items() if any(v and v in text for v in vals)]
    for name, rx in regexes.items():
        if f.parent.name == "openapi" and name in ("email", "cloud host"):
            continue  # upstream OpenAPI text contains example addresses and hosts
        if rx.search(text):
            hits.append(name)
    if f.name == "verify_fixtures.py":
        hits = [h for h in hits if h not in ("cloud host", "profile uid", "email")]
    if hits:
        bad += 1
        print(f"{f.relative_to(ROOT)}: {hits}")
print("fixtures clean" if not bad else f"{bad} file(s) need attention")
