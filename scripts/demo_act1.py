#!/usr/bin/env python3
"""Act 1, define and standardize: one issue becomes an observed service; one UI edit becomes a pull request (dev).

Usage: python3 scripts/demo_act1.py [--pause] [--dry-run] [--step NAME] [--availability 99.99]
       make demo-act1 [PAUSE=1] [STEP=issue] [DRY_RUN=1]

Beats, in order (kind in brackets):
  issue        [issue]     find or file the "Onboard a service" issue for field-service at 99.99; if its pull
                           request is missing and no onboard-service run is going, re-run the job for the issue.
                           Does nothing once the onboarding pull request has merged in this session
  ui-edit      [manual]    add a panel to the Grid dispatch triage dashboard in dev Kibana
  sync         [manual]    ask the platform assistant in dev chat to sync the dashboard; shows the capture-dev run
  review       [read]      the onboarding pull request's dev plan comment and the AI review of the target
  fix-target   [manual]    edit field-service.yaml on the pull request to 99.5 and merge; shows the apply-dev run
  capture-pr   [read]      the capture pull request and its import-only plan
  observed     [read]      the field-service dashboard and SLOs in dev once apply-dev finishes
  capture      [dispatch]  on demand: run capture-dev for the dashboard by hand (the assistant's fallback)

Every beat is safe to re-run: it finds the issue, pull request or run it made before. Common options are described
in scripts/demo_common.py.
"""
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import demo_common as dc  # noqa: E402
import kibana  # noqa: E402
from onboard_service import parse_form  # noqa: E402

NEW_SERVICE = "field-service"
ONBOARD_BRANCH = f"onboard/{NEW_SERVICE}"
CATALOG_FILE = f"modules/bundle/catalog/services/{NEW_SERVICE}.yaml"
TRIAGE_ID = "7f3c9a52-4e1b-4d8a-9c6e-2b5f8d1a0e47"  # scripts/seed_ui_dashboard.py
TRIAGE_TITLE = "Grid dispatch triage"
CAPTURE_PR_TITLE = "Capture dashboard: grid-dispatch-triage"  # scripts/capture.py: "Capture <type>: <slug>"
ASSISTANT = "gitops-platform-assistant"
P95_PANEL = ('FROM traces-* | WHERE service.name == "grid-dispatch" AND kind == "Server" '
             "| STATS p95_ms = ROUND(PERCENTILE(duration, 95) / 1000000) BY service.version")


def form(availability):
    """The issue body GitHub renders from .github/ISSUE_TEMPLATE/onboard-service.yml (headings are the labels)."""
    fields = [
        ("Service name", NEW_SERVICE),
        ("Description", "Schedules and tracks field work orders"),
        ("Owning team", "field-operations"),
        ("Tier", "2"),
        ("On-call contact email", "field-ops-oncall@example.com"),
        ("Runbook URL", "https://example.com/runbooks/field-service"),
        ("Availability SLO target (%)", availability),
        ("Latency threshold (ms)", "500"),
        ("Latency SLO target (% of requests under the threshold)", "95"),
        ("Release gate, maximum error ratio", "0.02"),
        ("Release gate, maximum p95 latency (ms)", "650"),
    ]
    return "\n\n".join(f"### {label}\n\n{value}" for label, value in fields) + "\n"


def onboarding_issue(d):
    issues = d.gh("issue", "list", "--label", "onboard-service", "--state", "open", "--limit", "50",
                  "--json", "number,title,body,url,createdAt") or []
    return next((i for i in issues if parse_form(i.get("body") or "").get("name") == NEW_SERVICE), None)


def onboarding_pr(d, state="open"):
    """The newest onboarding pull request in a state; merged ones count only from this session."""
    pr = next(iter(d.prs(state=state, head=ONBOARD_BRANCH)), None)
    if pr and state == "merged" and dc.parse_time(pr["mergedAt"]) < d.since:
        return None
    return pr


def issue(d):
    done = onboarding_pr(d, state="merged")
    if done:  # merging closed the issue; filing another would only re-render the old target onto the branch
        d.say(f"{NEW_SERVICE} is already onboarded: pull request #{done['number']} merged.")
        d.say("make demo-reset starts over.")
        d.link("Onboarding pull request", done["url"])
        return
    found = onboarding_issue(d)
    filed_now = False
    if found:
        d.say(f"Found issue #{found['number']}: {found['title']}")
    else:
        body = form(d.args.availability)
        d.say(f"Form: {NEW_SERVICE}, team field-operations, tier 2, availability {d.args.availability}")
        if d.act_on(f"file the onboarding issue for {NEW_SERVICE} (label onboard-service)"):
            url = d.gh("issue", "create", "--title", f"Onboard service: {NEW_SERVICE}", "--label", "onboard-service",
                       "--body-file", "-", input_text=body, parse=False)
            found = {"number": url.rstrip("/").rsplit("/", 1)[-1], "url": url, "createdAt": dc.utcnow().isoformat()}
            filed_now = True
    if found:
        d.link("Issue", found["url"])
    else:
        d.link("New issue form", d.github("/issues/new?template=onboard-service.yml"))

    pr = onboarding_pr(d)
    if not pr and found:
        going = d.find_run("onboard-service.yml", after=dc.parse_time(found["createdAt"]) - timedelta(seconds=30))
        if going and going["status"] != "completed":
            d.show_run("onboard-service run", going)
        elif not filed_now:
            d.dispatch("onboard-service.yml", {"issue": found["number"]})
        pr = d.wait_for("the onboarding pull request", lambda: onboarding_pr(d), interval=5)
    if pr:
        d.link("Onboarding pull request", pr["url"])
        d.link("Checks", pr["url"] + "/checks")
    d.link("onboard-service runs", d.actions("onboard-service.yml"))


def ui_edit(d):
    exists = d.elastic_call("dev", "reading the triage dashboard",
                            lambda: kibana.kibana("GET", f"/api/dashboards/{TRIAGE_ID}"), missing=False)
    if exists is False:
        d.warn(f"{TRIAGE_TITLE} is not in dev. Run make demo-reset (seed-dashboard) or scripts/seed_ui_dashboard.py.")
    d.manual([
        "Edit, then add a panel: p95 latency by version. ES|QL:",
        f"  {P95_PANEL}",
        "Save the dashboard.",
    ], links=[(TRIAGE_TITLE, d.kibana_link("dev", f"/app/dashboards#/view/{TRIAGE_ID}"))])


def sync(d):
    asked = dc.utcnow() - timedelta(seconds=60)
    d.manual([
        f'Ask: "Sync my {TRIAGE_TITLE} dashboard to Git."',
        "The assistant runs the sync-to-git workflow, which asks GitHub for a capture pull request.",
    ], links=[("Platform assistant chat", d.kibana_link("dev", f"/app/agent_builder/agents/{ASSISTANT}")),
              ("sync-to-git executions", d.execution_link("dev", "gitops-sync-to-git"))])
    run = d.wait_for("the capture-dev run", lambda: d.find_run("capture-dev.yml", after=asked), timeout=180, interval=5)
    if run:
        d.show_run("capture-dev run", run)
    else:
        d.link("capture-dev runs", d.actions("capture-dev.yml"))
        d.say("Fallback: make demo-act1 STEP=capture")


def review(d):
    pr = onboarding_pr(d)
    if not pr:
        d.warn("No open onboarding pull request. Run make demo-act1 STEP=issue.")
        d.link("Onboarding pull requests", d.github("/pulls?q=is%3Apr+label%3Aonboard-service"))
        return

    def comments():
        fresh = d.pr(pr["number"])
        plan, ai = d.comment_with_marker(fresh, "dev-plan"), d.comment_with_marker(fresh, "ai-review")
        return (plan, ai) if plan and ai else None

    both = d.wait_for("the dev plan and the AI review", comments, interval=15)
    if both:
        plan, ai = both
    else:
        fresh = d.pr(pr["number"])
        plan, ai = d.comment_with_marker(fresh, "dev-plan"), d.comment_with_marker(fresh, "ai-review")
    d.link("Pull request", pr["url"])
    if plan:
        headline = next((line.strip("* ") for line in plan.splitlines() if line.startswith("**")), "posted")
        d.say(f"Dev plan: {headline}")
    if ai:
        lines = [line for line in ai.splitlines() if line.strip() and not line.startswith("## ")]
        d.say(f"AI review ({'mentions' if '99.99' in ai else 'does not mention'} 99.99):")
        for line in lines[:6]:
            d.say(f"  {line[:160]}")
    if not both:
        d.say("Still waiting on a comment: the review is advisory; keep going and come back.")


def fix_target(d):
    pr = onboarding_pr(d)
    edit = ("Edit the catalog entry", d.github(f"/edit/{ONBOARD_BRANCH}/{CATALOG_FILE}"))
    merged = None
    if pr:
        d.manual([
            "availability_target: 99.99 -> 99.5, commit to the pull request branch.",
            "Wait for the checks to go green, then Merge.",
        ], links=[edit, ("Pull request", pr["url"])])
        merged = d.wait_merged(pr["number"], "the onboarding pull request to merge")
    else:
        merged = onboarding_pr(d, state="merged")
        if not merged:
            d.warn("No onboarding pull request. Run make demo-act1 STEP=issue.")
            d.link(*edit)
            return
        d.say(f"Already merged: #{merged['number']}")
    if merged:
        run = d.push_run("apply-dev.yml", merged["mergeCommit"]["oid"])
        if run:
            d.show_run("apply-dev run", run)
    d.link("apply-dev runs", d.actions("apply-dev.yml"))


def capture_pr(d):
    def find():
        return next((p for p in d.prs(label="ui-capture") if p["title"] == CAPTURE_PR_TITLE), None)

    pr = d.wait_for("the capture pull request", find, interval=10)
    if not pr:
        d.link("ui-capture pull requests", d.github("/pulls?q=is%3Apr+label%3Aui-capture"))
        return
    d.link("Capture pull request", pr["url"])
    plan = d.wait_for("its dev plan", lambda: d.comment_with_marker(d.pr(pr["number"]), "dev-plan"), interval=15)
    if plan:
        headline = next((line.strip("* ") for line in plan.splitlines() if line.startswith("**")), "posted")
        d.say(f"Dev plan: {headline}")
    d.say("Merge it too.")


def observed(d):
    merged = onboarding_pr(d, state="merged")
    if merged:
        run = d.find_run("apply-dev.yml", event="push", head_sha=merged["mergeCommit"]["oid"],
                         since=dc.parse_time(merged["mergedAt"]))
        if run and run["status"] != "completed":
            run = d.wait_run(run, "apply-dev to finish")
        if run:
            d.show_run("apply-dev run", run)
    d.link("Golden signals dashboard", d.kibana_link("dev", f"/app/dashboards#/view/svc-{NEW_SERVICE}-golden-signals"))
    for kind in ("availability", "latency"):
        slo_id = f"svc-{NEW_SERVICE}-{kind}"
        d.link(f"SLO {kind}", d.kibana_link("dev", f"/app/slos/{slo_id}"))
        target = d.slo_target("dev", slo_id)
        if target is False:
            d.warn(f"{slo_id} is not in dev yet")
        elif target is not None:
            d.say(f"{slo_id}: target {target}%")


def capture(d):
    run = d.find_run("capture-dev.yml", since=dc.utcnow() - timedelta(minutes=10))
    if run and (run["status"] != "completed" or run["conclusion"] == "success"):
        d.say("Reusing the latest capture-dev run.")
    else:
        run = d.dispatch("capture-dev.yml", {"object_type": "dashboard", "object_title": TRIAGE_TITLE,
                                             "note": "Added a p95 latency by version panel"})
    if run:
        d.show_run("capture-dev run", run)
    d.link("capture-dev runs", d.actions("capture-dev.yml"))


BEATS = [
    dc.Beat("issue", "issue", "File one issue: onboard field-service", issue),
    dc.Beat("ui-edit", "manual", "Add a panel to the Grid dispatch triage dashboard", ui_edit),
    dc.Beat("sync", "manual", "Ask the platform assistant to sync it to Git", sync),
    dc.Beat("review", "read", "Plan comment and AI review on the onboarding pull request", review),
    dc.Beat("fix-target", "manual", "Fix the target to 99.5 and merge", fix_target),
    dc.Beat("capture-pr", "read", "Capture pull request: import only", capture_pr),
    dc.Beat("observed", "read", "field-service observed in dev", observed),
    dc.Beat("capture", "dispatch", "Fallback: run capture-dev by hand", capture, on_demand=True),
]


if __name__ == "__main__":
    p = dc.parser(__doc__, BEATS)
    p.add_argument("--availability", default="99.99", help="availability target filed on the form (default 99.99)")
    dc.run_beats("Act 1: define and standardize (dev)", BEATS, p.parse_args())
