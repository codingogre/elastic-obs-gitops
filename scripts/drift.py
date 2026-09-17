#!/usr/bin/env python3
"""Classify prod drift from a saved plan and report it.

Usage:
  drift.py classify plan.json [--out drift.json]   exit 0 no drift, 10 revertible, 20 needs a human
  drift.py report drift.json --status reverted|needs_human|failed [--started-at ISO] [--run-url URL]

classify reads `terraform show -json` output. Only objects listed in the plan's resource_drift count; merged but
unapplied configuration is reported as pending and never applied here. Drifted objects are sorted:
  update  (someone edited a managed object)         revertible in place
  create  (someone deleted a managed object)        revertible, recreated with the same ID
  delete / replace                                   needs a human
The redacted evidence (changed attribute paths with before and after values; sensitive values masked) goes to
drift.json.

report emits drift_detected and drift_reverted events, opens or updates a GitHub issue per drifted object
(gh CLI, GH_TOKEN), asks the gitops-reviewer agent for a short explanation (advisory; skipped on error), and posts
a Teams card through the gitops-post-card workflow. It prints no credentials.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kibana  # noqa: E402
import plan_summary  # noqa: E402

ID_ATTRIBUTES = ("slo_id", "dashboard_id", "rule_id", "policy_id", "workflow_id", "agent_id", "tool_id", "skill_id",
                 "connector_id", "gate_id", "key", "name")


def object_id(resource_change):
    for source in (resource_change["change"].get("before") or {}, resource_change["change"].get("after") or {}):
        for attr in ID_ATTRIBUTES:
            value = source.get(attr)
            if isinstance(value, str) and value:
                return value
    return resource_change["address"]


def classify(plan):
    """Only objects Terraform saw change outside Terraform (plan resource_drift) are drift.

    A plan against prod can also carry configuration that is merged but not yet applied, for example a promotion
    waiting for its approver. Those changes are reported as pending and are never applied by the drift job.
    """
    by_address = {rc["address"]: rc for rc in plan.get("resource_changes", [])}
    drifted = {rd["address"]: rd["change"]["actions"] for rd in plan.get("resource_drift", [])}
    items, pending = [], []
    for row in plan_summary.summarize(plan):
        rc = by_address[row["address"]]
        if row["address"] not in drifted:
            pending.append({"address": row["address"], "action": row["action"]})
            continue
        action = row["action"]
        kind = "revertible" if action in ("update", "create") else "needs_human"
        items.append({
            "address": row["address"],
            "object_id": object_id(rc),
            "type": rc["type"],
            "action": action,
            "drift": "deleted outside Terraform" if drifted[row["address"]] == ["delete"] else "edited outside Terraform",
            "kind": kind,
            "changes": row["changes"][:25],
        })
    if not items:
        status = "none"
    elif any(i["kind"] == "needs_human" for i in items):
        status = "needs_human"
    else:
        status = "revertible"
    return {
        "status": status,
        "items": items,
        "revert_targets": [i["address"] for i in items if i["kind"] == "revertible"],
        "pending_unapplied": pending,
        "detected_at": datetime.now(timezone.utc).isoformat(),
    }


def cmd_classify(args):
    with open(args.plan_json) as f:
        result = classify(json.load(f))
    with open(args.out, "w") as f:
        json.dump(result, f, indent=1, default=str)
    print(f"drift: {result['status']} ({len(result['items'])} object(s))")
    if result["pending_unapplied"]:
        print(f"drift: {len(result['pending_unapplied'])} merged change(s) not yet applied; left for apply-prod")
    if args.targets_file:
        with open(args.targets_file, "w") as f:
            f.write("".join(f"-target={a}\n" for a in result["revert_targets"]))
    for item in result["items"]:
        paths = ", ".join(c["path"] for c in item["changes"][:5]) or "-"
        print(f"  {item['action']:>7}  {item['object_id']}  [{paths}]")
    sys.exit({"none": 0, "revertible": 10, "needs_human": 20}[result["status"]])


def explain(item):
    """Two or three sentences from the reviewer agent; advisory, never blocks."""
    prompt = (
        "A scheduled Terraform plan found this change in the production observability project, made outside Git. "
        "In two or three plain sentences for a GitHub issue, say what was changed, what it would have meant for "
        "operations if it had stayed, and that the pipeline reverted it to the reviewed version. No preamble, "
        "no headings, no verdict line.\n\n" + json.dumps(item, default=str)[:6000]
    )
    try:
        reply = kibana.kibana("POST", "/api/agent_builder/converse",
                              {"agent_id": "gitops-reviewer", "input": prompt}, timeout=180)
        text = (reply.get("response") or {}).get("message", "").strip()
        conversation = reply.get("conversation_id")
        if conversation:
            try:
                kibana.kibana("DELETE", f"/api/agent_builder/conversations/{conversation}")
            except Exception:
                pass
        return text
    except Exception as e:
        print(f"drift: explanation unavailable ({e.__class__.__name__})")
        return ""


def gh(*argv, input_text=None):
    return subprocess.run(["gh", *argv], input=input_text, text=True, capture_output=True, check=True).stdout.strip()


def upsert_issue(title, body, labels):
    repo = os.environ["GITHUB_REPOSITORY"]
    found = gh("issue", "list", "--repo", repo, "--state", "open", "--search", f'"{title}" in:title',
               "--json", "number,title", "--jq", f'.[] | select(.title == "{title}") | .number')
    if found:
        number = found.splitlines()[0]
        gh("issue", "comment", number, "--repo", repo, "--body-file", "-", input_text=body)
        return f"{os.environ['GITHUB_SERVER_URL']}/{repo}/issues/{number}"
    return gh("issue", "create", "--repo", repo, "--title", title, "--label", ",".join(labels), "--body-file", "-",
              input_text=body)


def fmt_value(v):
    return plan_summary.short(v, 80)


def cmd_report(args):
    with open(args.drift_json) as f:
        drift = json.load(f)
    if drift["status"] == "none":
        print("drift: nothing to report")
        return
    env = os.environ.get("GITOPS_ENV", "prod")
    started = args.started_at or drift["detected_at"]
    duration = max(0.0, (datetime.now(timezone.utc) - datetime.fromisoformat(started.replace("Z", "+00:00"))).total_seconds())
    reverted = args.status == "reverted"

    for item in drift["items"]:
        details = json.dumps({"paths": [c["path"] for c in item["changes"]], "action": item["action"]})
        subprocess.run([sys.executable, str(Path(__file__).parent / "emit_event.py"), "--action", "drift_detected",
                        "--env", env, "--resource-address", item["address"], "--details", details], check=False)
        if reverted:
            subprocess.run([sys.executable, str(Path(__file__).parent / "emit_event.py"), "--action", "drift_reverted",
                            "--env", env, "--resource-address", item["address"], "--started-at", started,
                            "--details", details], check=False)

        explanation = explain(item) if args.explain else ""
        change_lines = [f"| `{c['path']}` | `{fmt_value(c['before'])}` | `{fmt_value(c['after'])}` |" for c in item["changes"]]
        verb = {"reverted": "Drift reverted", "needs_human": "Drift needs a human", "failed": "Drift revert failed"}[args.status]
        title = f"{verb}: {item['object_id']}"
        body = "\n".join([
            f"**{verb}** in `{env}`: `{item['address']}` ({item['action']}).",
            "",
            explanation or "",
            "",
            # In a drift plan, before is what prod has and after is what Git says.
            "| Attribute | Found in prod | Git (restored) |" if item["action"] == "update" else "| Attribute | Before | After |",
            "|---|---|---|",
            *change_lines,
            "",
            f"Time to revert: {duration:.0f} s." if reverted else "Destructive drift is never applied automatically.",
            f"Run: {args.run_url}" if args.run_url else "",
            "",
            "Values marked (sensitive) are redacted. Found by the drift-prod job.",
        ])
        labels = ["drift"]
        issue_url = ""
        if os.environ.get("GITHUB_ACTIONS") == "true":
            try:
                issue_url = upsert_issue(title, body, labels)
                print(f"drift: issue {issue_url}")
            except subprocess.CalledProcessError as e:
                print(f"drift: could not write the issue: {e.stderr.strip()[:300]}")
        else:
            print(body)

        first = item["changes"][0] if item["changes"] else {"path": "-", "before": None, "after": None}
        card = {
            "title": f"{verb} · {env}",
            "subtitle": f"{item['object_id']} · {item['drift']}",
            "badge": "DRIFT CONTROL · " + {"reverted": "REVERTED", "needs_human": "NEEDS A HUMAN", "failed": "REVERT FAILED"}[args.status],
            "status": "good" if reverted else "attention",
            "text": (explanation.split("\n")[0][:400] if explanation else
                     ("Prod matches Git again. The GitHub issue has the full diff." if reverted
                      else "The pipeline did not apply this change. Someone needs to look at it.")),
            "facts": [
                {"title": "Resource", "value": item["object_id"]},
                {"title": "Change", "value": f"{first['path']}: {fmt_value(first['before'])} → {fmt_value(first['after'])}"
                 if item["action"] == "update" else item["action"]},
                {"title": "Reverted in" if reverted else "Status", "value": f"{duration:.0f} s" if reverted else args.status},
                {"title": "By", "value": "drift-prod pipeline"},
            ],
            "links": [link for link in ([{"title": "Open issue", "url": issue_url}] if issue_url else [])
                      + ([{"title": "Open run", "url": args.run_url}] if args.run_url else [])],
        }
        try:
            execution = kibana.run_workflow("gitops-post-card", card, timeout_s=180)
            print(f"drift: card workflow {execution.get('status')}")
        except Exception as e:
            print(f"drift: card not posted ({e})")
        time.sleep(1)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    c = sub.add_parser("classify")
    c.add_argument("plan_json")
    c.add_argument("--out", default="drift.json")
    c.add_argument("--targets-file", help="write one -target=<address> line per revertible object")
    r = sub.add_parser("report")
    r.add_argument("drift_json")
    r.add_argument("--status", required=True, choices=["reverted", "needs_human", "failed"])
    r.add_argument("--started-at")
    r.add_argument("--run-url", default="")
    r.add_argument("--no-explain", dest="explain", action="store_false")
    args = p.parse_args()
    {"classify": cmd_classify, "report": cmd_report}[args.command](args)


if __name__ == "__main__":
    main()
