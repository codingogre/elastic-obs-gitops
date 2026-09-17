"""Minimal Kibana and Elasticsearch HTTP helpers for the pipeline scripts.

Reads KIBANA_ENDPOINT, KIBANA_API_KEY, KIBANA_SPACE, ELASTICSEARCH_ENDPOINTS and ELASTICSEARCH_API_KEY from the
environment (scripts/with_env.py locally, Environment secrets in CI). Never logs credentials.
"""
import json
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

_CAFILE = "/etc/ssl/cert.pem"


def _ctx():
    return ssl.create_default_context(cafile=_CAFILE) if os.path.exists(_CAFILE) else ssl.create_default_context()


class HTTPError(Exception):
    def __init__(self, method, path, status, body):
        super().__init__(f"{method} {path} -> HTTP {status}: {body[:500]}")
        self.status, self.body = status, body


def _request(base, auth, method, path, body=None, headers=None, timeout=60, retries=3):
    data = None if body is None else json.dumps(body).encode()
    hdrs = {"Authorization": f"ApiKey {auth}", "Content-Type": "application/json", **(headers or {})}
    for attempt in range(retries + 1):
        req = urllib.request.Request(base.rstrip("/") + path, data=data, method=method, headers=hdrs)
        try:
            with urllib.request.urlopen(req, context=_ctx(), timeout=timeout) as resp:
                raw = resp.read().decode()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            text = e.read().decode(errors="replace")
            if e.code in (429, 502, 503) and attempt < retries:
                time.sleep(2 ** attempt)
                continue
            raise HTTPError(method, path, e.code, text) from None
        except urllib.error.URLError:
            if attempt < retries:
                time.sleep(2 ** attempt)
                continue
            raise


def space():
    return os.environ.get("KIBANA_SPACE") or "default"


def space_path(path):
    s = space()
    return path if s == "default" else f"/s/{s}{path}"


def kibana(method, path, body=None, internal=False, timeout=60, in_space=True):
    headers = {"kbn-xsrf": "true"}
    if internal:
        headers["x-elastic-internal-origin"] = "Kibana"
    full = space_path(path) if in_space else path
    return _request(os.environ["KIBANA_ENDPOINT"], os.environ["KIBANA_API_KEY"], method, full, body, headers, timeout)


def elasticsearch(method, path, body=None, timeout=60):
    base = os.environ["ELASTICSEARCH_ENDPOINTS"].split(",")[0]
    return _request(base, os.environ["ELASTICSEARCH_API_KEY"], method, path, body, None, timeout)


def kibana_url(path=""):
    """Browser URL inside the configured space."""
    return os.environ["KIBANA_ENDPOINT"].rstrip("/") + space_path(path)


def run_workflow(workflow_id, inputs, timeout_s=900, poll_s=5):
    """Run a saved workflow and wait for a terminal status. Returns the execution with step outputs."""
    started = kibana("POST", f"/api/workflows/workflow/{urllib.parse.quote(workflow_id)}/run", {"inputs": inputs})
    execution_id = started["workflowExecutionId"]
    deadline = time.time() + timeout_s
    terminal = {"completed", "failed", "cancelled", "timed_out", "skipped"}
    while True:
        execution = kibana("GET", f"/api/workflows/executions/{execution_id}?includeOutput=true")
        if execution.get("status") in terminal:
            execution["id"] = execution_id
            return execution
        if time.time() > deadline:
            raise TimeoutError(f"workflow {workflow_id} execution {execution_id} still {execution.get('status')}")
        time.sleep(poll_s)
