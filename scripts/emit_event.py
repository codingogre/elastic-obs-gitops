#!/usr/bin/env python3
"""Index one pipeline event into the gitops-events data stream.

Usage:
  emit_event.py --action apply --env dev --outcome success [--service grid-dispatch] [--version 2.5.0]
                [--bundle-version obs-v0.3.0] [--resource-address ADDR]... [--started-at ISO8601]
                [--verdict pass|warn|fail] [--reason TEXT]... [--details JSON] [--message TEXT]

Reads ELASTICSEARCH_ENDPOINTS and ELASTICSEARCH_API_KEY from the environment. In GitHub Actions the run URL,
actor, run ID and commit are filled in automatically. Prints the document ID, never credentials.
"""
import argparse
import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

ACTIONS = ["plan", "apply", "tag", "promotion", "capture", "drift_detected", "drift_reverted", "gate_evaluated",
           "release_started", "release_succeeded", "rollback", "remediation", "onboarded"]


def ssl_context():
    cafile = "/etc/ssl/cert.pem"
    return ssl.create_default_context(cafile=cafile) if os.path.exists(cafile) else ssl.create_default_context()


def build_event(args):
    now = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    gitops = {
        "env": args.env,
        "bundle_version": args.bundle_version,
        "service": args.service,
        "service_version": args.version,
        "baseline_version": args.baseline_version,
        "resource_address": args.resource_address or None,
        "verdict": args.verdict,
        "reasons": args.reason or None,
        "started_at": args.started_at,
        "duration_s": args.duration_s,
        "pr_number": args.pr_number,
        "details": json.loads(args.details) if args.details else None,
    }
    if os.environ.get("GITHUB_ACTIONS") == "true":
        server, repo, run_id = os.environ["GITHUB_SERVER_URL"], os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_RUN_ID"]
        gitops.update({
            "actor": os.environ.get("GITHUB_ACTOR"),
            "run_id": run_id,
            "run_url": f"{server}/{repo}/actions/runs/{run_id}",
            "commit": os.environ.get("GITHUB_SHA"),
        })
    else:
        gitops["actor"] = os.environ.get("USER")
    return {
        "@timestamp": now,
        "message": args.message or f"{args.action} {args.outcome} in {args.env}",
        "event": {"action": args.action, "outcome": args.outcome},
        "gitops": {k: v for k, v in gitops.items() if v is not None},
    }


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--action", required=True, choices=ACTIONS)
    p.add_argument("--env", required=True)
    p.add_argument("--outcome", default="success", choices=["success", "failure", "unknown"])
    p.add_argument("--service")
    p.add_argument("--version")
    p.add_argument("--baseline-version")
    p.add_argument("--bundle-version")
    p.add_argument("--resource-address", action="append")
    p.add_argument("--verdict", choices=["pass", "warn", "fail"])
    p.add_argument("--reason", action="append")
    p.add_argument("--started-at", help="ISO 8601 start time; the ingest pipeline derives duration_s from it. "
                                        "For a promotion it is the first commit the release brings, so duration_s is "
                                        "the lead time; for drift_reverted it is the detection time")
    p.add_argument("--duration-s", type=float)
    p.add_argument("--pr-number", type=int)
    p.add_argument("--details", help="JSON object stored as flattened gitops.details")
    p.add_argument("--message")
    args = p.parse_args()

    endpoint = os.environ["ELASTICSEARCH_ENDPOINTS"].split(",")[0].rstrip("/")
    doc = build_event(args)
    req = urllib.request.Request(
        f"{endpoint}/gitops-events/_doc",
        data=json.dumps(doc).encode(),
        method="POST",
        headers={"Authorization": f"ApiKey {os.environ['ELASTICSEARCH_API_KEY']}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, context=ssl_context(), timeout=30) as resp:
            body = json.load(resp)
    except urllib.error.HTTPError as e:
        sys.exit(f"emit_event: HTTP {e.code}: {e.read().decode()[:500]}")
    print(f"gitops-events {args.action} {args.outcome} -> {body.get('_id')}")


if __name__ == "__main__":
    main()
