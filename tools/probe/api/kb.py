"""Shared helpers for the Phase 0 API probes (stdlib only).

Run every probe through scripts/with_env.py so credentials come from the environment:

    python3 scripts/with_env.py dev -- python3 tools/probe/api/<probe>.py

Credentials are read from KIBANA_ENDPOINT / KIBANA_API_KEY (and ELASTICSEARCH_* for the
identity lookup used by the sanitizer). They are never printed or written. Fixtures are
sanitized before they are saved: hostnames become https://kibana.example, and API keys,
user names, e-mail addresses and user-profile UIDs are replaced with placeholders.
"""
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURES = HERE.parent / "fixtures"
CTX = ssl.create_default_context(cafile="/etc/ssl/cert.pem")

KB = os.environ.get("KIBANA_ENDPOINT", "").rstrip("/")
KEY = os.environ.get("KIBANA_API_KEY", "")
ES = (os.environ.get("ELASTICSEARCH_ENDPOINTS", "").split(",")[0]).rstrip("/")
ES_KEY = os.environ.get("ELASTICSEARCH_API_KEY", "") or KEY

if not KB or not KEY:
    sys.exit("KIBANA_ENDPOINT and KIBANA_API_KEY must be set (run through scripts/with_env.py)")

# Keys whose values identify a person or a credential. Values are replaced, keys are kept,
# so the fixture still shows which fields the server manages.
SECRET_KEYS = {
    "api_key", "apikey", "apiKey", "api_key_id", "apiKeyId", "apiKeyOwner", "api_key_owner",
    "created_by", "createdBy", "updated_by", "updatedBy", "username", "user_name",
    "userName", "full_name", "fullName", "email", "profile_uid", "profileUid", "uid",
    "createdByUid", "updatedByUid", "authorization", "Authorization",
}
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# Kibana user-profile UIDs (created_by, access_control.owner, ...)
PROFILE_UID = re.compile(r"\bu_[A-Za-z0-9_-]{20,}")
_identity = []


def _hosts():
    hosts = set()
    for url in (KB, ES):
        m = re.match(r"https?://([^/:]+)", url or "")
        if m:
            hosts.add(m.group(1))
            # project prefix without the service part, e.g. <name>.kb / <name>.es
            hosts.add(m.group(1).split(".")[0])
    return hosts


def identity_strings():
    """Names of the authenticated principal (API key name, id, owner) so they can be scrubbed."""
    if _identity:
        return _identity
    names = set()
    if ES:
        try:
            req = urllib.request.Request(f"{ES}/_security/_authenticate",
                                         headers={"Authorization": f"ApiKey {ES_KEY}"})
            with urllib.request.urlopen(req, context=CTX, timeout=30) as r:
                d = json.load(r)
            for v in (d.get("username"), d.get("full_name"), d.get("email"),
                      (d.get("api_key") or {}).get("name"), (d.get("api_key") or {}).get("id")):
                if isinstance(v, str) and len(v) >= 4:
                    names.add(v)
        except Exception:
            pass
    _identity.extend(sorted(names, key=len, reverse=True))
    return _identity


def scrub_str(s):
    if not isinstance(s, str):
        return s
    if KEY and KEY in s:
        s = s.replace(KEY, "<redacted-api-key>")
    for url in (KB, ES):
        if url:
            s = s.replace(url, "https://kibana.example" if url == KB else "https://elasticsearch.example")
    for h in _hosts():
        if len(h) > 12:
            s = s.replace(h, "kibana.example")
    for name in identity_strings():
        s = s.replace(name, "<redacted-user>")
    s = EMAIL.sub("<redacted-email>", s)
    s = PROFILE_UID.sub("<redacted-profile-uid>", s)
    return s


def sanitize(obj):
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in SECRET_KEYS and v not in (None, "", [], {}):
                out[k] = "<redacted>" if not isinstance(v, (dict, list)) else sanitize_struct(v)
            else:
                out[k] = sanitize(v)
        return out
    if isinstance(obj, list):
        return [sanitize(v) for v in obj]
    return scrub_str(obj)


def sanitize_struct(v):
    """Keep the shape of a nested identity object but blank every leaf."""
    if isinstance(v, dict):
        return {k: sanitize_struct(x) for k, x in v.items()}
    if isinstance(v, list):
        return [sanitize_struct(x) for x in v]
    return "<redacted>" if v not in (None, "") else v


def call(method, path, body=None, space=None, internal=False, headers=None, raw=None, timeout=120):
    """Return (status, parsed_json_or_text, elapsed_seconds, response_headers)."""
    prefix = f"/s/{space}" if space and space != "default" else ""
    url = f"{KB}{prefix}{path}"
    h = {"Authorization": f"ApiKey {KEY}", "kbn-xsrf": "true", "Accept": "application/json"}
    if internal:
        h["x-elastic-internal-origin"] = "Kibana"
    data = None
    if raw is not None:
        data = raw if isinstance(raw, bytes) else raw.encode()
        h["Content-Type"] = "application/json"
    elif body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, context=CTX, timeout=timeout) as r:
            status, text, rh = r.status, r.read().decode("utf-8", "replace"), dict(r.headers)
    except urllib.error.HTTPError as e:
        status, text, rh = e.code, e.read().decode("utf-8", "replace"), dict(e.headers)
    elapsed = round(time.monotonic() - t0, 2)
    try:
        parsed = json.loads(text) if text.strip() else None
    except json.JSONDecodeError:
        parsed = text
    return status, parsed, elapsed, rh


def es_call(method, path, body=None, timeout=120):
    """Elasticsearch request. Return (status, parsed_json_or_text, elapsed_seconds)."""
    if not ES:
        sys.exit("ELASTICSEARCH_ENDPOINTS must be set")
    h = {"Authorization": f"ApiKey {ES_KEY}", "Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{ES}{path}", data=data, method=method, headers=h)
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, context=CTX, timeout=timeout) as r:
            status, text = r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        status, text = e.code, e.read().decode("utf-8", "replace")
    elapsed = round(time.monotonic() - t0, 2)
    try:
        parsed = json.loads(text) if text.strip() else None
    except json.JSONDecodeError:
        parsed = text
    return status, parsed, elapsed


def es_fire(api, name, method, path, body=None, note=None, limit=1500):
    status, resp, elapsed = es_call(method, path, body=body)
    save(api, name, method, path, status, resp, request=body, note=note, elapsed=elapsed)
    show(f"ES {method} {path}", status, resp, limit, elapsed)
    return status, resp


def save(api, name, method, path, status, response, request=None, space=None, note=None, elapsed=None):
    """Write a sanitized request/response pair to fixtures/<api>/<name>.json."""
    d = FIXTURES / api
    d.mkdir(parents=True, exist_ok=True)
    prefix = f"/s/{space}" if space and space != "default" else ""
    doc = {"request": {"method": method, "path": f"{prefix}{path}"}}
    if request is not None:
        doc["request"]["body"] = sanitize(request)
    doc["response"] = {"status": status, "body": sanitize(response)}
    if elapsed is not None:
        doc["response"]["elapsed_seconds"] = elapsed
    if note:
        doc["note"] = note
    try:
        text = json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
        text.encode("utf-8")
    except UnicodeEncodeError:  # lone surrogates in a server message
        text = json.dumps(doc, indent=2, ensure_ascii=True) + "\n"
    (d / f"{name}.json").write_text(text)
    return doc


def show(label, status, body, limit=1500, elapsed=None):
    text = json.dumps(sanitize(body), ensure_ascii=False) if not isinstance(body, str) else scrub_str(body)
    text = text.encode("utf-8", "backslashreplace").decode("utf-8")
    t = f" {elapsed}s" if elapsed is not None else ""
    print(f"--- {label}: HTTP {status}{t}\n{text[:limit]}")


def fire(api, name, method, path, body=None, space=None, internal=False, note=None, limit=1500,
         headers=None, raw=None, timeout=120):
    """call + save + show in one step."""
    status, resp, elapsed, _ = call(method, path, body=body, space=space, internal=internal,
                                    headers=headers, raw=raw, timeout=timeout)
    req = body if raw is None else raw
    save(api, name, method, path, status, resp, request=req, space=space, note=note, elapsed=elapsed)
    show(f"{method} {('/s/' + space) if space and space != 'default' else ''}{path}", status, resp, limit, elapsed)
    return status, resp
