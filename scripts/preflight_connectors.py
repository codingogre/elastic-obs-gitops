#!/usr/bin/env python3
"""End-to-end connector preflight: drive every response-tool connector through Kibana and clean up after it.

Usage:
  with_env.py <dev|prod> -- python3 scripts/preflight_connectors.py --env dev|prod
                                                                   [--only servicenow,pagerduty,teams,github]

Every check calls POST /s/<space>/api/actions/connector/<id>/_execute and passes only when Kibana answers HTTP 200
AND the body says status "ok" (Kibana answers 200 even when the target system rejected the call).

  servicenow  pushToService opens "[GITOPS-DEMO] Connector preflight <UTC time>" with correlation_id
              gitops-preflight-<epoch>, closeIncident closes it by that correlation_id, and getIncident reads
              the state back (7 = Closed).
  pagerduty   eventAction trigger with dedupKey gitops-preflight-<epoch>, then resolve. With PD_API_TOKEN set
              (a read-only PagerDuty REST token), the incident is also found and its status read back.
  teams       posts a small Adaptive Card 1.4. Skipped when the connector does not exist in this environment.
              Power Automate answers 202 before its flow runs, so only the channel message proves delivery.
  github      repository_dispatch (event_type connector-preflight) through the .http connector; GitHub must
              answer 204. No workflow listens to that event type.

Reads KIBANA_ENDPOINT, KIBANA_API_KEY and KIBANA_SPACE from the environment. Prints connector names, statuses
and record numbers or links, never credentials. Exits 1 when any check fails.
"""
import argparse
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Fixed connector IDs, identical in every environment (docs/CONVENTIONS.md, modules/bundle/main.tf).
CONNECTORS = {
    "servicenow": "846af0d6-5963-4c2d-b510-f48d525999f8",
    "pagerduty": "49d5a547-b980-426b-a5a4-f00f3ab6e473",
    "teams": "abd684be-bb1c-4dec-81ba-ce4e6922bad3",
    "github": "e5ab5e5b-6f2b-488a-b140-a474987298bf",
}
DEFAULT_SPACE = {"dev": "gitops-dev", "prod": "default"}
PREFIX = "[GITOPS-DEMO]"
SECRET_ENV = ["KIBANA_API_KEY", "ELASTICSEARCH_API_KEY", "TEAMS_WEBHOOK_URL", "SN_USER", "SN_PASSWORD",
              "PD_ROUTING_KEY", "GH_DISPATCH_TOKEN", "PD_API_TOKEN", "TF_VAR_teams_webhook_url", "TF_VAR_sn_user",
              "TF_VAR_sn_password", "TF_VAR_pd_routing_key", "TF_VAR_github_dispatch_token"]


def ssl_context():
    cafile = "/etc/ssl/cert.pem"
    return ssl.create_default_context(cafile=cafile) if os.path.exists(cafile) else ssl.create_default_context()


CTX = ssl_context()


def redact(text):
    """Remove any credential value (and signed webhook URLs) from text that is about to be printed."""
    text = str(text)
    for name in SECRET_ENV:
        value = os.environ.get(name, "")
        if len(value) >= 6:
            text = text.replace(value, "<redacted>")
    return re.sub(r"https://[^\s\"']*(sig=|/workflows/)[^\s\"']*", "<redacted-url>", text)


def http(method, url, headers, body=None, timeout=120):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, context=CTX, timeout=timeout) as r:
            raw = r.read()
            code = r.status
    except urllib.error.HTTPError as e:
        raw, code = e.read(), e.code
    try:
        return code, json.loads(raw) if raw else None
    except ValueError:
        return code, raw.decode(errors="replace")


class Kibana:
    def __init__(self, space):
        self.base = os.environ["KIBANA_ENDPOINT"].rstrip("/") + ("" if space == "default" else f"/s/{space}")
        self.headers = {"Authorization": "ApiKey " + os.environ["KIBANA_API_KEY"], "kbn-xsrf": "true",
                        "Content-Type": "application/json"}

    def connector(self, connector_id):
        return http("GET", f"{self.base}/api/actions/connector/{connector_id}", self.headers)

    def execute(self, connector_id, params):
        return http("POST", f"{self.base}/api/actions/connector/{connector_id}/_execute", self.headers,
                    {"params": params})


class Report:
    def __init__(self):
        self.failures = 0

    def line(self, ok, name, text):
        mark = "ok  " if ok is True else ("skip" if ok is None else "FAIL")
        if ok is False:
            self.failures += 1
        print(f"  [{mark}] {name:<24} {redact(text)}", flush=True)


def executed(report, name, step, code, body):
    """True when Kibana answered 200 and the connector reported status ok; reports the failure otherwise."""
    if code == 200 and isinstance(body, dict) and body.get("status") == "ok":
        return True
    if isinstance(body, dict):
        detail = f"HTTP {code} status={body.get('status')} message={body.get('message')!r} " \
                 f"service_message={body.get('service_message')!r}"
    else:
        detail = f"HTTP {code} {str(body)[:300]!r}"
    report.line(False, name, f"{step}: {detail}")
    return False


def check_servicenow(kb, report, name, stamp, epoch):
    cid = CONNECTORS["servicenow"]
    correlation = f"gitops-preflight-{epoch}"
    code, body = kb.execute(cid, {
        "subAction": "pushToService",
        "subActionParams": {
            "incident": {
                "short_description": f"{PREFIX} Connector preflight {stamp}",
                "description": "Created by the Elastic connector preflight to prove Kibana can open and close "
                               "incidents. It is closed again by the same run.",
                "correlation_id": correlation,
                "correlation_display": "Elastic connector preflight",
                "severity": "3",
                "urgency": "3",
                "impact": "3",
            },
            "comments": [],
        },
    })
    if not executed(report, name, "pushToService", code, body):
        return
    data = body.get("data") or {}
    number, sys_id, link = data.get("title"), data.get("id"), data.get("url")
    report.line(True, name, f"opened {number}  {link}")

    code, body = kb.execute(cid, {
        "subAction": "closeIncident",
        "subActionParams": {"incident": {"correlation_id": correlation, "externalId": None}},
    })
    if not executed(report, name, "closeIncident", code, body):
        report.line(False, name, f"{number} is still open: close it in ServiceNow")
        return
    if not body.get("data"):
        report.line(False, name, f"closeIncident found no incident for correlation_id {correlation}")
        return

    code, body = kb.execute(cid, {"subAction": "getIncident", "subActionParams": {"externalId": sys_id}})
    if not executed(report, name, "getIncident", code, body):
        return
    incident = body.get("data") or {}
    state, close_code = str(incident.get("state")), incident.get("close_code")
    if state == "7":
        report.line(True, name, f"closed {number}  (state 7 Closed, close_code {close_code!r})")
    else:
        report.line(False, name, f"{number} read back with state {state!r} after closeIncident; close it by hand")


def pd_api(path):
    return http("GET", "https://api.pagerduty.com" + path, {
        "Authorization": "Token token=" + os.environ["PD_API_TOKEN"],
        "Accept": "application/vnd.pagerduty+json;version=2",
    }, timeout=30)


def pd_find_incident(dedup_key, since):
    """Find the incident whose alert carries dedup_key (Events API incidents keep it on the alert)."""
    query = urllib.parse.urlencode({"since": since, "sort_by": "created_at:desc", "limit": 25})
    code, body = pd_api(f"/incidents?{query}")
    if code != 200 or not isinstance(body, dict):
        return None, f"PagerDuty REST API answered HTTP {code}"
    for incident in body.get("incidents", []):
        code, alerts = pd_api(f"/incidents/{incident['id']}/alerts")
        if code == 200 and any(a.get("alert_key") == dedup_key for a in alerts.get("alerts", [])):
            return incident, None
    return None, "not found yet"


def check_pagerduty(kb, report, name, stamp, epoch):
    cid = CONNECTORS["pagerduty"]
    dedup = f"gitops-preflight-{epoch}"
    since = datetime.fromtimestamp(epoch - 60, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    code, body = kb.execute(cid, {
        "eventAction": "trigger",
        "dedupKey": dedup,
        "summary": f"{PREFIX} Connector preflight",
        "severity": "info",
        "source": "Elastic connector preflight",
        "customDetails": {"sent_at": stamp},
    })
    if not executed(report, name, "trigger", code, body):
        return
    data = body.get("data") or {}
    report.line(True, name, f"triggered dedup_key {data.get('dedup_key', dedup)}  ({data.get('message')})")

    incident = None
    if os.environ.get("PD_API_TOKEN"):
        deadline = time.time() + 60
        while time.time() < deadline and incident is None:
            time.sleep(4)
            incident, _ = pd_find_incident(dedup, since)
        if incident:
            report.line(True, name, f"incident #{incident['incident_number']} {incident['status']}  "
                                    f"{incident.get('html_url')}")
        else:
            report.line(False, name, f"no PagerDuty incident carries dedup_key {dedup} after 60 s")

    code, body = kb.execute(cid, {"eventAction": "resolve", "dedupKey": dedup})
    if not executed(report, name, "resolve", code, body):
        report.line(False, name, f"dedup_key {dedup} is still open: resolve it in PagerDuty")
        return
    data = body.get("data") or {}
    if not os.environ.get("PD_API_TOKEN"):
        report.line(True, name, f"resolved dedup_key {data.get('dedup_key', dedup)}  ({data.get('message')}; "
                                "set PD_API_TOKEN to read the incident status back)")
        return
    if incident is None:
        return
    status, deadline = None, time.time() + 60
    while time.time() < deadline:
        code, fresh = pd_api(f"/incidents/{incident['id']}")
        status = (fresh or {}).get("incident", {}).get("status") if code == 200 else None
        if status == "resolved":
            break
        time.sleep(4)
    if status == "resolved":
        report.line(True, name, f"incident #{incident['incident_number']} resolved")
    else:
        report.line(False, name, f"incident #{incident['incident_number']} read back as {status!r} after resolve")


def check_teams(kb, report, name, stamp, env):
    card = {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.4",
        "body": [
            {"type": "TextBlock", "text": f"{PREFIX} Connector preflight", "weight": "Bolder", "size": "Medium",
             "wrap": True},
            {"type": "FactSet", "facts": [{"title": "Sent", "value": f"{stamp} from the {env} environment"}]},
        ],
    }
    code, body = kb.execute(CONNECTORS["teams"], {"message": json.dumps(card)})
    if executed(report, name, "post card", code, body):
        report.line(True, name, "card accepted by the webhook (Power Automate answers 202 before its flow runs: "
                                "only the channel message proves delivery)")


def github_repository(env):
    if os.environ.get("GITHUB_REPOSITORY"):
        return os.environ["GITHUB_REPOSITORY"]
    tfvars = REPO / "envs" / env / "terraform.tfvars"
    match = re.search(r'^\s*github_repository\s*=\s*"([^"]+)"', tfvars.read_text(), re.M) if tfvars.exists() else None
    if not match:
        sys.exit("Set GITHUB_REPOSITORY (owner/repo): it is not in envs/<env>/terraform.tfvars")
    return match.group(1)


def check_github(kb, report, name, stamp, env):
    repo = github_repository(env)
    code, body = kb.execute(CONNECTORS["github"], {
        "method": "POST",
        "path": f"/repos/{repo}/dispatches",
        "body": {"event_type": "connector-preflight", "client_payload": {"source": "preflight", "sent_at": stamp}},
    })
    if not executed(report, name, "repository_dispatch", code, body):
        return
    upstream = (body.get("data") or {}).get("status")
    if upstream == 204:
        report.line(True, name, f"repository_dispatch connector-preflight accepted by {repo} (GitHub HTTP 204)")
    else:
        report.line(False, name, f"GitHub answered HTTP {upstream} instead of 204")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--env", required=True, choices=["dev", "prod"])
    p.add_argument("--only", default=",".join(CONNECTORS),
                   help="comma-separated subset of: " + ",".join(CONNECTORS))
    args = p.parse_args()

    only = [c.strip() for c in args.only.split(",") if c.strip()]
    unknown = sorted(set(only) - set(CONNECTORS))
    if unknown:
        p.error(f"unknown connector(s) in --only: {', '.join(unknown)}")
    for var in ("KIBANA_ENDPOINT", "KIBANA_API_KEY"):
        if not os.environ.get(var):
            sys.exit(f"{var} is not set: run through scripts/with_env.py {args.env} -- ...")
    space = os.environ.get("KIBANA_SPACE") or DEFAULT_SPACE[args.env]
    if space != DEFAULT_SPACE[args.env]:
        sys.exit(f"KIBANA_SPACE is {space!r} but --env {args.env} expects {DEFAULT_SPACE[args.env]!r}: "
                 "are these the right credentials?")

    kb = Kibana(space)
    report = Report()
    now = datetime.now(timezone.utc)
    stamp, epoch = now.strftime("%Y-%m-%d %H:%M:%S UTC"), int(now.timestamp())
    print(f"Connector preflight  env={args.env}  space={space}  {stamp}")

    for key in only:
        code, connector = kb.connector(CONNECTORS[key])
        if code == 404:
            if key == "teams":
                report.line(None, "gitops-teams", "connector not configured in this environment")
            else:
                report.line(False, f"gitops-{key}", f"connector {CONNECTORS[key]} does not exist in space {space}")
            continue
        if code != 200 or not isinstance(connector, dict):
            report.line(False, key, f"reading connector {CONNECTORS[key]}: HTTP {code}")
            continue
        name = connector.get("name", key)
        if connector.get("is_missing_secrets"):
            report.line(False, name, "Kibana reports missing secrets: re-apply with a bumped secrets_version")
            continue
        try:
            if key == "servicenow":
                check_servicenow(kb, report, name, stamp, epoch)
            elif key == "pagerduty":
                check_pagerduty(kb, report, name, stamp, epoch)
            elif key == "teams":
                check_teams(kb, report, name, stamp, args.env)
            elif key == "github":
                check_github(kb, report, name, stamp, args.env)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            report.line(False, name, f"request failed: {exc}")

    print("All connector checks passed." if not report.failures else f"{report.failures} connector check(s) failed.")
    sys.exit(1 if report.failures else 0)


if __name__ == "__main__":
    main()
