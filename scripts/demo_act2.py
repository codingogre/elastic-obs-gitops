#!/usr/bin/env python3
"""Act 2, promote and protect: prod moves one release forward through a gated pull request; a bad release is blocked.

Usage: python3 scripts/demo_act2.py [--pause] [--dry-run] [--step NAME] [--skip-soak] [--degrade-after 180]
       make demo-act2 [PAUSE=1] [STEP=bad-release] [DEGRADE_AFTER=180] [DRY_RUN=1]

Beats, in order (kind in brackets):
  promote         [dispatch]  find the open promotion pull request, or wait for apply-dev to tag the release and
                              run promote.yml
  checks          [read]      prod plan, release gate and AI review on the promotion pull request
  approve         [manual]    merge it; shows the apply-prod run (dispatched when PROD_LIVE is not "true") and
                              waits for the prod approval
  bad-release     [dispatch]  release-app: grid-dispatch 2.5.0 at 15% errors in prod
  prod-dashboard  [read]      apply-prod done: the Grid dispatch triage dashboard in prod, same ID as dev
  gate-result     [read]      the release-app run fails its gate; the gate execution and its Teams step
  teams           [manual]    the "Release blocked" card in Teams
  latent-bug      [dispatch]  presenter only: start grid-dispatch 2.5.1, which degrades after --degrade-after
                              seconds so its alert lands during Act 3 (also make demo-act3 STEP=latent-bug)

Every beat is safe to re-run: it finds the pull request or run it made before. Common options are described in
scripts/demo_common.py.
"""
import base64
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import demo_common as dc  # noqa: E402
import kibana  # noqa: E402

TRIAGE_ID = "7f3c9a52-4e1b-4d8a-9c6e-2b5f8d1a0e47"  # captured in Act 1; same ID in both environments
RELEASE_TAG = re.compile(r"ref=(obs-v\d+\.\d+\.\d+)")


def promotion_pr(d, state="open"):
    return next(iter(d.prs(state=state, label="promotion")), None)


def prod_ref(d):
    """The bundle release envs/prod/main.tf pins on main, or None while prod uses the local bundle."""
    content = d.gh("api", f"repos/{d.repo}/contents/envs/prod/main.tf?ref=main", "--jq", ".content", parse=False)
    match = RELEASE_TAG.search(base64.b64decode(content).decode())
    return match.group(1) if match else None


def newest_tag(d):
    out = d.git("ls-remote", "--tags", "--refs", "origin", "obs-v*")
    tags = [line.rsplit("refs/tags/", 1)[1] for line in out.splitlines() if "refs/tags/" in line]
    return max(tags, key=lambda t: tuple(int(n) for n in t[len("obs-v"):].split(".")), default=None)


def promote(d):
    pr = promotion_pr(d)
    if not pr:
        tagging = [r for r in d.runs("apply-dev.yml", limit=5) if r["status"] != "completed"]
        if tagging:
            d.show_run("apply-dev run (tags the release)", tagging[0])
            d.wait_run(tagging[0], "apply-dev to tag the release")
        tag, current = newest_tag(d), prod_ref(d)
        d.say(f"Newest bundle release {tag}; prod runs {current or 'the local bundle (not promoted yet)'}.")
        if tag and tag == current:
            merged = promotion_pr(d, state="merged")
            if merged and dc.parse_time(merged["mergedAt"]) >= d.since:
                d.say("Already promoted in this session.")
                d.link("Promotion pull request", merged["url"])
            else:
                d.say("Prod already runs the newest release: nothing to promote. Merge the Act 1 pull requests first.")
            return
        run = d.find_run("promote.yml", since=dc.utcnow())
        if run:
            d.show_run("promote run", run)
        else:
            run = d.dispatch("promote.yml", {"skip_soak": "true"} if d.args.skip_soak else {})
            if run:
                d.show_run("promote run", run)
        pr = d.wait_for("the promotion pull request", lambda: promotion_pr(d), interval=10)
    if pr:
        d.link("Promotion pull request", pr["url"])
        d.link("Files (envs/prod/main.tf)", pr["url"] + "/files")
    d.link("promote runs", d.actions("promote.yml"))


def checks(d):
    pr = promotion_pr(d)
    if not pr:
        d.warn("No open promotion pull request. Run make demo-act2 STEP=promote.")
        return

    def settled():
        rows = d.pr_checks(pr["number"])
        return rows if rows and all(r["bucket"] != "pending" for r in rows) else None

    rows = d.wait_for("the promotion checks", settled, interval=15) or d.pr_checks(pr["number"])
    for row in rows:
        d.link(f"{row['name']} ({row['bucket']})", row["link"])
    fresh = d.pr(pr["number"])
    for marker, label in (("prod-plan", "Prod plan"), ("ai-review", "AI review")):
        body = d.comment_with_marker(fresh, marker)
        if not body:
            d.say(f"{label}: not posted yet")
            continue
        first = next((line.strip("* ") for line in body.splitlines()
                      if line.strip() and not line.startswith("#")), "posted")
        d.say(f"{label}: {first[:160]}")
    d.link("Pull request", pr["url"])


def approve(d):
    pr = promotion_pr(d)
    if pr:
        d.manual(["Merge the promotion pull request.",
                  "apply-prod then waits for its approver: open the run, Review deployments, Approve."],
                 links=[("Promotion pull request", pr["url"])])
        merged = d.wait_merged(pr["number"], "the promotion to merge")
    else:
        merged = promotion_pr(d, state="merged")
        if merged and dc.parse_time(merged["mergedAt"]) < d.since:
            merged = None
    if not merged:
        d.warn("No promotion merged in this session.")
        d.link("apply-prod runs", d.actions("apply-prod.yml"))
        return

    run = dc.apply_prod_run(d, merged)
    if not run:
        d.link("apply-prod runs", d.actions("apply-prod.yml"))
        return
    d.show_run("apply-prod run", run)
    d.say("Review deployments -> prod -> Approve.")
    run = d.wait_run(run, "the prod approval", until="started")
    d.show_run("apply-prod run", run)


def bad_release(d):
    d.say(f"{dc.SERVICE} {dc.BAD_VERSION} ships at 15% errors; the gate compares it with {dc.BASELINE_VERSION}.")
    dc.start_release(d, dc.BAD_VERSION, "0.15")


def prod_dashboard(d):
    run = d.find_run("apply-prod.yml")
    if run:
        if run["status"] != "completed":
            run = d.wait_run(run, "apply-prod to finish")
        d.show_run("apply-prod run", run)
    exists = d.elastic_call("prod", "reading the triage dashboard",
                            lambda: kibana.kibana("GET", f"/api/dashboards/{TRIAGE_ID}"), missing=False)
    if exists is False:
        d.warn("Grid dispatch triage is not in prod yet: apply-prod has not finished or the capture was not promoted.")
    d.link("Prod: Grid dispatch triage", d.kibana_link("prod", f"/app/dashboards#/view/{TRIAGE_ID}"))
    d.link("Dev: Grid dispatch triage", d.kibana_link("dev", f"/app/dashboards#/view/{TRIAGE_ID}"))
    d.say(f"Same ID in both URLs: {TRIAGE_ID}")


def gate_result(d):
    title = f"release {dc.SERVICE} {dc.BAD_VERSION} to prod"
    run = d.find_run("release-app.yml", title=title)
    if not run:
        d.warn(f"No {title} run. Run make demo-act2 STEP=bad-release.")
        return
    if run["status"] != "completed":
        run = d.wait_run(run, "the release gate verdict")
    d.show_run("release-app run", run)
    if run["conclusion"] == "failure":
        d.say(f"Blocked: {dc.SERVICE} stays on {dc.BASELINE_VERSION}. The job summary lists the reasons.")

    for execution in (d.executions("prod", "gitops-release-gate", size=5) or []):
        full = d.execution("prod", execution["id"])
        context = (full or {}).get("context") or {}
        if (context.get("inputs") or {}).get("version") != dc.BAD_VERSION:
            continue
        output = context.get("output") or {}
        d.link("Gate execution", d.execution_link("prod", "gitops-release-gate", execution["id"]))
        d.say(f"Verdict: {output.get('verdict', execution.get('status'))}")
        reasons = output.get("reasons") or []
        for reason in [reasons] if isinstance(reasons, str) else reasons:
            d.say(f"  - {reason}")
        card = dc.step(full, "post_card")
        d.say(f"Teams card step: {card.get('status') if card else 'not reached'}")
        break
    else:
        d.link("Gate executions", d.execution_link("prod", "gitops-release-gate"))


def teams(d):
    d.manual(['Teams, platform-gitops: the "Release blocked" card with the reasons and links.',
              "No card? The gate execution's post_card step output is the proof."],
             links=[("Gate executions", d.execution_link("prod", "gitops-release-gate"))])


def latent_bug(d):
    dc.start_latent_bug(d)


BEATS = [
    dc.Beat("promote", "dispatch", "Promotion pull request", promote),
    dc.Beat("checks", "read", "Prod plan, release gate and AI review", checks),
    dc.Beat("approve", "manual", "Merge and approve apply-prod", approve),
    dc.Beat("bad-release", "dispatch", "Ship grid-dispatch 2.5.0 at 15% errors", bad_release),
    dc.Beat("prod-dashboard", "read", "Prod applied: same dashboard, same ID", prod_dashboard),
    dc.Beat("gate-result", "read", "The gate fails the release", gate_result),
    dc.Beat("teams", "manual", '"Release blocked" in Teams', teams),
    dc.Beat("latent-bug", "dispatch", "Presenter only: start grid-dispatch 2.5.1 for Act 3", latent_bug),
]


if __name__ == "__main__":
    p = dc.parser(__doc__, BEATS)
    p.add_argument("--skip-soak", action="store_true", help="promote without the dev soak before the gate")
    dc.add_release_args(p)
    dc.run_beats("Act 2: promote and protect (dev -> prod)", BEATS, p.parse_args())
