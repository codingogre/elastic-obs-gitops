#!/usr/bin/env python3
"""Capture an object built in the dev UI into Git and open a pull request.

Usage:
  capture.py --object-type dashboard (--object-id ID | --object-title TITLE) [--note TEXT] [--requested-by WHO]
  capture.py --object-type workflow --object-id ID [...]
  Add --no-pr to write files and plan locally without touching Git.

Steps: resolve the object in the dev space; refuse golden-path objects (those change through their template, so an
issue is opened instead); write it under modules/bundle/bespoke/ (dashboards as Dashboards API JSON normalized by the
elasticgitops data source, workflows as their exact YAML); add an import block to envs/dev/imports.tf so dev adopts
the existing object instead of recreating it; run the dev plan, which must show only imports; then commit to a
capture/<timestamp>-<slug> branch and open a pull request labelled ui-capture (plus needs-attention when the plan
shows more than imports). Credentials come from the environment (scripts/with_env.py dev, or CI secrets).
"""
import argparse
import json
import os
import re
import subprocess
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kibana  # noqa: E402
import plan_summary  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
BESPOKE = REPO / "modules/bundle/bespoke"
IMPORTS = REPO / "envs/dev/imports.tf"
SCRATCH = REPO / "tools/capture/scratch"
MANAGED_PREFIXES = ("svc-", "ops-", "gitops-")


def run(cmd, cwd=REPO, check=True, capture=True):
    result = subprocess.run(cmd, cwd=cwd, text=True, capture_output=capture)
    if check and result.returncode != 0:
        sys.exit(f"capture: {' '.join(cmd[:3])} failed:\n{(result.stderr or result.stdout)[-2000:]}")
    return result


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "object"


def resolve_dashboard(object_id, title):
    if object_id:
        found = kibana.kibana("GET", f"/api/dashboards/{urllib.parse.quote(object_id)}")
        return object_id, found.get("data", {}).get("title") or object_id
    listing = kibana.kibana("GET", "/api/dashboards?" + urllib.parse.urlencode({"search": title, "per_page": 100}))
    items = listing.get("dashboards") or listing.get("items") or listing.get("data") or []
    exact = [d for d in items if (d.get("data") or {}).get("title", d.get("title", "")).lower() == title.lower()]
    if len(exact) != 1:
        names = sorted({(d.get("data") or {}).get("title", d.get("title", "")) for d in items})
        sys.exit(f"capture: expected exactly one dashboard titled {title!r} in space {kibana.space()}, "
                 f"found {len(exact)}. Close matches: {names[:10]}")
    return exact[0]["id"], (exact[0].get("data") or {}).get("title", exact[0].get("title"))


def read_dashboard(object_id):
    """The elasticgitops data source strips server defaults exactly as the resource does."""
    env = dict(os.environ, TF_VAR_space_id=kibana.space(), TF_VAR_dashboard_id=object_id,
               TF_IN_AUTOMATION="true")
    for cmd in (["terraform", "init", "-input=false", "-backend=false"],
                ["terraform", "apply", "-input=false", "-auto-approve", "-refresh=true"]):
        result = subprocess.run(cmd, cwd=SCRATCH, env=env, text=True, capture_output=True)
        if result.returncode != 0:
            sys.exit(f"capture: reading the dashboard failed:\n{result.stderr[-2000:]}")
    out = subprocess.run(["terraform", "output", "-json"], cwd=SCRATCH, env=env, text=True, capture_output=True,
                         check=True)
    for leftover in SCRATCH.glob("terraform.tfstate*"):
        leftover.unlink()
    outputs = json.loads(out.stdout)
    return json.loads(outputs["dashboard_json"]["value"])


def write_dashboard(slug, object_id, data):
    path = BESPOKE / "dashboards" / f"{slug}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"id": object_id, "data": data}, indent=2, ensure_ascii=False) + "\n")
    return path, f'module.bundle.module.bespoke.elasticgitops_dashboard.this["{slug}"]'


def write_workflow(object_id):
    found = kibana.kibana("GET", f"/api/workflows/workflow/{urllib.parse.quote(object_id)}")
    path = BESPOKE / "workflows" / f"{object_id}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(found["yaml"])
    return path, f'module.bundle.module.bespoke.elasticstack_kibana_agentbuilder_workflow.this["{object_id}"]'


def add_import(address, object_id):
    block = f'\nimport {{\n  to = {address}\n  id = "{kibana.space()}/{object_id}"\n}}\n'
    text = IMPORTS.read_text() if IMPORTS.exists() else ""
    if address not in text:
        IMPORTS.write_text(text + block)


def dev_plan():
    env = dict(os.environ, TF_IN_AUTOMATION="true")
    plan = REPO / "envs/dev/capture.tfplan"
    result = subprocess.run([sys.executable, "scripts/with_env.py", "dev", "--", "terraform", "-chdir=envs/dev", "plan",
                             "-input=false", "-lock-timeout=5m", f"-out={plan.name}"],
                            cwd=REPO, env=env, text=True, capture_output=True)
    if result.returncode != 0:
        return None, f"The dev plan failed:\n\n```\n{result.stderr[-3000:]}\n```\n", False
    shown = subprocess.run(["terraform", "-chdir=envs/dev", "show", "-json", plan.name], cwd=REPO, env=env,
                           text=True, capture_output=True, check=True)
    plan.unlink(missing_ok=True)
    rows = plan_summary.summarize(json.loads(shown.stdout))
    imports_only = all(r["action"] == "import" or (r["importing"] and not r["changes"]) for r in rows)
    return rows, plan_summary.to_markdown(rows, "Dev plan", 40000), imports_only


def open_issue_for_managed(object_type, object_id, title, note):
    body = (f"Someone asked to capture `{object_id}` ({title}) from the dev UI, but it belongs to the platform's "
            f"golden path, which changes through its template in `modules/bundle/service-observability`, not per "
            f"object. The next dev apply puts it back to the template.\n\nNote from the request: {note or '-'}\n\n"
            f"If the change is worth keeping for every service, change the template in a pull request.")
    run(["gh", "issue", "create", "--title", f"UI edit on a golden-path asset: {object_id}", "--body", body])
    print(f"capture: {object_id} is managed by the golden path; opened an issue instead")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--object-type", choices=["dashboard", "workflow"], default="dashboard")
    p.add_argument("--object-id", default="")
    p.add_argument("--object-title", default="")
    p.add_argument("--note", default="")
    p.add_argument("--requested-by", default="")
    p.add_argument("--no-pr", action="store_true")
    args = p.parse_args()
    if not args.object_id and not args.object_title:
        sys.exit("capture: give --object-id or --object-title")

    if args.object_type == "dashboard":
        object_id, title = resolve_dashboard(args.object_id, args.object_title)
    else:
        object_id, title = args.object_id, args.object_id

    if object_id.startswith(MANAGED_PREFIXES):
        if args.no_pr:
            sys.exit(f"capture: {object_id} is a golden-path object; it changes through its template")
        open_issue_for_managed(args.object_type, object_id, title, args.note)
        return

    slug = slugify(title) if args.object_type == "dashboard" else object_id
    if args.object_type == "dashboard":
        path, address = write_dashboard(slug, object_id, read_dashboard(object_id))
    else:
        path, address = write_workflow(object_id)
    add_import(address, object_id)
    print(f"capture: wrote {path.relative_to(REPO)} and the import for {address}")

    rows, plan_md, imports_only = dev_plan()
    print(plan_md)
    if args.no_pr:
        return

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    branch = f"capture/{stamp}-{slug}"
    run(["git", "checkout", "-B", branch])
    run(["git", "add", str(path.relative_to(REPO)), str(IMPORTS.relative_to(REPO))])
    run(["git", "commit", "-m", f"Capture {args.object_type}: {slug}", "-m",
         f"Captured from the dev UI ({object_id}).{' Requested by ' + args.requested_by + '.' if args.requested_by else ''}"])
    run(["git", "push", "--force", "origin", branch])

    verdict = ("The plan only adopts the existing object: nothing is recreated or changed." if imports_only
               else "**The plan shows more than an import.** Review the residual changes below before merging.")
    body = "\n".join([
        f"Captures the {args.object_type} **{title}** (`{object_id}`) from the dev UI into Git.",
        "",
        f"- Requested by: {args.requested_by or 'the capture workflow'}",
        f"- Note: {args.note or '-'}",
        f"- Where: dev Kibana, space `{kibana.space()}`, {args.object_type}s",
        f"- File: `{path.relative_to(REPO)}`",
        "",
        verdict,
        "",
        plan_md,
        "After merge, the dev apply is a no-op and the next promotion creates the same object, with the same ID, in prod.",
    ])
    labels = "ui-capture" + ("" if imports_only else ",needs-attention")
    url = run(["gh", "pr", "create", "--base", "main", "--head", branch, "--title",
               f"Capture {args.object_type}: {slug}", "--label", labels, "--body", body]).stdout.strip()
    print(f"capture: {url}")
    subprocess.run([sys.executable, str(Path(__file__).parent / "emit_event.py"), "--action", "capture", "--env", "dev",
                    "--resource-address", address, "--details", json.dumps({"object_id": object_id, "pr": url})],
                   check=False)


if __name__ == "__main__":
    main()
