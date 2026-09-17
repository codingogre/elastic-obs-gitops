#!/usr/bin/env python3
"""Put the demo back to the tag demo-baseline: Git, both projects, the UI-made dashboard and baseline traffic.

Usage: python3 scripts/demo_reset.py [--dry-run] [--step NAME] [--skip A,B] [--pids-file PATH] [--restart-traffic]
       python3 scripts/demo_reset.py --set-baseline [--baseline-ref origin/main] [--force]
       make demo-reset [DRY_RUN=1] [STEP=traffic] [SKIP=merge,apply-prod]

Steps, in order (kind in brackets):
  close-leftovers  [github]    close open onboarding, capture and promotion pull requests and open onboarding and
                               drift issues, so the act drivers start from nothing
  revert-pr        [github]    one commit on a demo-reset/<time> branch that returns main's files to demo-baseline
                               (every commit since the tag, reverted through a reviewed pull request, never a force
                               push)
  merge            [github]    wait for the pull request's checks and merge it when they pass
  apply-dev        [dispatch]  the apply-dev run for the merge (dispatched when the push did not start one)
  apply-prod       [dispatch]  when envs/prod changed: the apply-prod run, which waits for its approver. Prod is
                               applied only by that job, never from here
  seed-dashboard   [local]     once main no longer holds the captured dashboard and apply-dev has applied that
                               successfully, re-seed "Grid dispatch triage" in dev
                               (scripts/seed_ui_dashboard.py --force)
  traffic          [local]     keep the baseline traffic generators running (dev and prod, three services): start
                               any that stopped or run other settings; --restart-traffic restarts all of them

Generators are laptop processes recorded in the pids file as "<env> <service> <pid>", with logs beside it as
<env>-<service>.log. --set-baseline tags --baseline-ref as demo-baseline and pushes the tag (--force moves it);
nothing else runs with it. A full run (no --step) ends by recording the reset time, so the act drivers never reuse a
rehearsal's runs. Every step is safe to re-run. Common options are described in scripts/demo_common.py.
"""
import os
import signal
import shutil
import subprocess
import sys
import time
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import demo_common as dc  # noqa: E402

REPO = dc.REPO
BASELINE_TAG = "demo-baseline"
RESET_BRANCH = "demo-reset/"
LEFTOVER_PR_LABELS = ("onboard-service", "ui-capture", "promotion")
LEFTOVER_ISSUE_LABELS = ("onboard-service", "drift")
TRIAGE_ID = "7f3c9a52-4e1b-4d8a-9c6e-2b5f8d1a0e47"  # scripts/seed_ui_dashboard.py
CAPTURED_DASHBOARDS = "modules/bundle/bespoke/dashboards"
# service, version, requests per second, error rate, p95 ms. At these rates the 99.5% SLOs stay achievable.
BASELINE_TRAFFIC = [
    ("grid-dispatch", "2.4.3", 5, 0.002, 250),
    ("turbine-telemetry", "3.1.0", 5, 0.002, 180),
    ("field-service", "1.0.0", 3, 0.003, 320),
]


# ── Git ──────────────────────────────────────────────────────────────────────
def remote_refs(d):
    """Commit SHAs of origin's main and demo-baseline (None when the tag does not exist)."""
    out = d.git("ls-remote", "origin", "refs/heads/main", f"refs/tags/{BASELINE_TAG}*")
    refs = {ref: sha for sha, ref in (line.split("\t") for line in out.splitlines())}
    # "^{}" is the commit an annotated tag points at.
    tag = refs.get(f"refs/tags/{BASELINE_TAG}^{{}}") or refs.get(f"refs/tags/{BASELINE_TAG}")
    return refs.get("refs/heads/main"), tag


def have(sha):
    return bool(sha) and subprocess.run(["git", "cat-file", "-e", f"{sha}^{{commit}}"], cwd=REPO,
                                        capture_output=True).returncode == 0


def open_reset_pr(d):
    return next((p for p in d.prs() if p["headRefName"].startswith(RESET_BRANCH)), None)


def merged_reset_pr(d):
    merged = next((p for p in d.prs(state="merged") if p["headRefName"].startswith(RESET_BRANCH)), None)
    return merged if merged and dc.parse_time(merged["mergedAt"]) >= d.since else None


def pr_files(d, number):
    return d.gh("pr", "view", str(number), "--json", "files", "--jq", "[.files[].path]") or []


def applies_dev(d, merged):
    """True when a merged pull request changed something apply-dev applies."""
    return any(f.startswith(("modules/", "envs/dev/")) for f in pr_files(d, merged["number"]))


def close_leftovers(d):
    closed = 0
    for label in LEFTOVER_PR_LABELS:
        for pr in d.prs(label=label):
            if d.act_on(f"close pull request #{pr['number']} {pr['title']!r}"):
                d.gh("pr", "close", str(pr["number"]), "--comment", "Closed by make demo-reset.", parse=False)
            closed += 1
    for label in LEFTOVER_ISSUE_LABELS:
        for issue in d.gh("issue", "list", "--label", label, "--state", "open", "--json", "number,title") or []:
            if d.act_on(f"close issue #{issue['number']} {issue['title']!r}"):
                d.gh("issue", "close", str(issue["number"]), "--comment", "Closed by make demo-reset.", parse=False)
            closed += 1
    if not closed:
        d.say("Nothing left open.")


def revert_pr(d):
    pr = open_reset_pr(d)
    if pr:
        d.say("A reset pull request is already open.")
        d.link("Reset pull request", pr["url"])
        return
    if not d.dry_run:
        d.git("fetch", "--quiet", "--tags", "--force", "origin", "main")
    main, base = remote_refs(d)
    if not base:
        d.warn(f"No {BASELINE_TAG} tag on origin. Create it once: python3 scripts/demo_reset.py --set-baseline")
        return
    if not (have(main) and have(base)):
        d.say(f"[dry run] main {main[:7]} or {BASELINE_TAG} {base[:7]} is not fetched here; a real run fetches first.")
        return
    if d.git("rev-parse", f"{main}^{{tree}}") == d.git("rev-parse", f"{base}^{{tree}}"):
        d.say(f"main already matches {BASELINE_TAG}: nothing to revert.")
        return
    commits = d.git("log", "--no-merges", "--pretty=- %h %s", f"{base}..{main}") or "- (merge commits only)"
    d.say(f"Commits on main since {BASELINE_TAG} ({base[:7]}):")
    for line in commits.splitlines():
        d.say(f"  {line}")
    branch = f"{RESET_BRANCH}{dc.utcnow():%Y%m%d-%H%M%S}"
    if not d.act_on(f"commit main's files back to {BASELINE_TAG} on {branch}, push the branch and open a pull request"):
        return
    # commit-tree builds the commit from the tag's tree without touching the working tree or the index.
    message = f"Reset the demo to {BASELINE_TAG}\n\nReverts every commit since {BASELINE_TAG} ({base[:7]}):\n{commits}"
    commit = d.git("commit-tree", f"{base}^{{tree}}", "-p", main, "-m", message)
    d.git("push", "--quiet", "origin", f"{commit}:refs/heads/{branch}")
    body = (f"Returns every file to the `{BASELINE_TAG}` tag ({base[:7]}), reverting:\n\n{commits}\n\n"
            "Merging applies dev through apply-dev and, when `envs/prod` changes, prod through apply-prod, which "
            "waits for its approver. Opened by `make demo-reset`.")
    url = d.gh("pr", "create", "--base", "main", "--head", branch, "--title", f"Reset demo to {BASELINE_TAG}",
               "--body", body, parse=False)
    d.link("Reset pull request", url)


def merge(d):
    pr = open_reset_pr(d)
    if not pr:
        done = merged_reset_pr(d)
        if done:
            d.say(f"Already merged: #{done['number']}")
        else:
            d.warn("No reset pull request. Run make demo-reset STEP=revert-pr.")
        return
    d.link("Reset pull request", pr["url"])

    def settled():
        rows = d.pr_checks(pr["number"])
        return rows if rows and all(r["bucket"] != "pending" for r in rows) else None

    rows = d.wait_for("its checks", settled, interval=20) or []
    blocking = [r for r in rows if r["bucket"] in ("fail", "cancel")]
    for row in blocking:
        d.link(f"{row['name']} ({row['bucket']})", row["link"])
    if blocking or not rows:
        d.warn("Not merged: checks failed or are still running. Merge it by hand when ready, then run "
               "make demo-reset SKIP=close-leftovers,revert-pr,merge")
        return
    if d.act_on(f"merge pull request #{pr['number']}"):
        d.gh("pr", "merge", str(pr["number"]), "--merge", parse=False)


def apply_dev(d):
    merged = merged_reset_pr(d)
    if not merged:
        d.warn(f"No reset pull request merged in the last {d.args.since_minutes} minutes.")
        d.link("apply-dev runs", d.actions("apply-dev.yml"))
        return
    if not applies_dev(d, merged):
        d.say("The reset changed nothing dev applies.")
        return
    run = (d.push_run("apply-dev.yml", merged["mergeCommit"]["oid"])
           or d.find_run("apply-dev.yml", event="workflow_dispatch", after=dc.parse_time(merged["mergedAt"]))
           or d.dispatch("apply-dev.yml"))
    if run:
        d.show_run("apply-dev run", run)
        if run["status"] != "completed":
            d.show_run("apply-dev run", d.wait_run(run, "apply-dev to finish"))


def apply_prod(d):
    merged = merged_reset_pr(d)
    if not merged:
        d.warn(f"No reset pull request merged in the last {d.args.since_minutes} minutes.")
        d.link("apply-prod runs", d.actions("apply-prod.yml"))
        return
    if not any(f.startswith("envs/prod/") for f in pr_files(d, merged["number"])):
        d.say("Prod's pinned bundle release did not change: nothing to apply.")
        return
    run = dc.apply_prod_run(d, merged)
    if not run:
        d.link("apply-prod runs", d.actions("apply-prod.yml"))
        return
    d.show_run("apply-prod run", run)
    d.say("Approve it: Review deployments -> prod -> Approve.")
    if run["status"] != "completed":
        d.show_run("apply-prod run", d.wait_run(run, "the approval and apply-prod to finish"))


# ── Dashboard ────────────────────────────────────────────────────────────────
def captured_on_main(d):
    try:
        paths = d.gh("api", f"repos/{d.repo}/contents/{CAPTURED_DASHBOARDS}?ref=main",
                     "--jq", '[.[] | select(.name | endswith(".json")) | .path]') or []
    except dc.GhError as e:
        if "404" in str(e) or "Not Found" in str(e):
            return []  # an empty folder is not in Git
        raise
    raw = "Accept: application/vnd.github.raw"
    return [path for path in paths
            if TRIAGE_ID in d.gh("api", f"repos/{d.repo}/contents/{path}?ref=main", "-H", raw, parse=False)]


def seed_dashboard(d):
    on_main = captured_on_main(d)
    if on_main:
        d.warn(f"main still holds the captured dashboard ({', '.join(on_main)}). Merge and apply the reset first.")
        return
    local = [f.name for f in (REPO / CAPTURED_DASHBOARDS).glob("*.json") if TRIAGE_ID in f.read_text()]
    if local:
        d.warn(f"This checkout still has the capture ({', '.join(local)}); the seed script refuses. Pull main first.")
        return
    # Until apply-dev has applied main without the capture, dev state still holds the dashboard and the next apply
    # would delete a re-seeded one. So the newest apply-dev must have succeeded, and be for the reset if there was one.
    latest = next((r for r in d.runs("apply-dev.yml", limit=10) if r.get("conclusion") != "skipped"), None)
    if latest and latest["status"] != "completed":
        latest = d.wait_run(latest, "apply-dev to finish before seeding")
    merged = merged_reset_pr(d)
    merged_at = dc.parse_time(merged["mergedAt"]) - timedelta(seconds=30) if merged else None
    if merged and applies_dev(d, merged) and (not latest or dc.parse_time(latest["createdAt"]) < merged_at):
        d.warn("apply-dev has not run for the reset yet. Run make demo-reset STEP=apply-dev, then STEP=seed-dashboard.")
        return
    if latest and (latest["status"] != "completed" or latest["conclusion"] != "success"):
        d.show_run("apply-dev run", latest)
        d.warn("Not seeded: the newest apply-dev did not succeed, so dev may still hold the capture. Fix and re-run "
               "apply-dev, then make demo-reset STEP=seed-dashboard.")
        return
    if d.act_on("re-seed Grid dispatch triage in dev (scripts/seed_ui_dashboard.py --force)"):
        result = subprocess.run([sys.executable, "scripts/with_env.py", "dev", "--", sys.executable,
                                 "scripts/seed_ui_dashboard.py", "--force"], cwd=REPO, text=True, capture_output=True)
        d.say((result.stdout.strip() or result.stderr.strip()[-500:]) or f"seed exited {result.returncode}")
    d.link("Grid dispatch triage", d.kibana_link("dev", f"/app/dashboards#/view/{TRIAGE_ID}"))


# ── Traffic ──────────────────────────────────────────────────────────────────
def traffic_args(env, spec):
    service, version, rps, error_rate, p95 = spec
    return ["scripts/traffic.py", "--env", env, "--service", service, "--version", version, "--rps", str(rps),
            "--error-rate", str(error_rate), "--p95-ms", str(p95), "--run-id", "baseline"]


def command_of(pid):
    """The process's command line, or "" when it is gone."""
    result = subprocess.run(["ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else ""


def stop(d, pid, label):
    if not d.act_on(f"stop {label} (pid {pid})"):
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    for _ in range(30):  # traffic.py flushes what is buffered on SIGTERM
        time.sleep(0.5)
        if not command_of(pid):
            return
    d.warn(f"{label} (pid {pid}) is still stopping")


def start(d, env, spec, log_dir):
    label = f"{env} {spec[0]} {spec[1]}"
    python = ".venv/bin/python" if (REPO / ".venv/bin/python").exists() else sys.executable
    command = ["python3", "scripts/with_env.py", env, "--", python, *traffic_args(env, spec)]
    if shutil.which("caffeinate"):  # keep the laptop awake while traffic runs
        command = ["caffeinate", "-i", *command]
    log = log_dir / f"{env}-{spec[0]}.log"
    if not d.act_on(f"start {label}: {' '.join(command)} >> {log}"):
        return None
    with open(log, "a") as out:
        process = subprocess.Popen(command, cwd=REPO, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                                   start_new_session=True)
    return process.pid


def traffic(d):
    pids_file = Path(d.args.pids_file)
    records = {}
    if pids_file.is_file():
        for line in pids_file.read_text().splitlines():
            parts = line.split()
            if len(parts) == 3 and parts[2].isdigit():
                records[(parts[0], parts[1])] = int(parts[2])
    if not d.dry_run:
        pids_file.parent.mkdir(parents=True, exist_ok=True)  # the logs go beside it
    kept = {}
    try:
        for env in ("dev", "prod"):
            for spec in BASELINE_TRAFFIC:
                label = f"{env} {spec[0]}"
                pid = records.pop((env, spec[0]), None)
                command = command_of(pid) if pid else ""
                # Only a traffic.py process for this environment and service is ever stopped.
                running = "scripts/traffic.py" in command and f"--env {env} --service {spec[0]} " in command
                if running and " ".join(traffic_args(env, spec)) in command and not d.args.restart_traffic:
                    d.say(f"{label}: running (pid {pid})")
                    kept[(env, spec[0])] = pid
                    continue
                if running:
                    stop(d, pid, label)
                new_pid = start(d, env, spec, pids_file.parent)
                if new_pid:
                    kept[(env, spec[0])] = new_pid
                    d.say(f"{label}: started (pid {new_pid})")
        for key in list(records):  # generators outside the baseline stay recorded while they run
            pid = records.pop(key)
            if "scripts/traffic.py" in command_of(pid):
                d.say(f"{key[0]} {key[1]}: not part of the baseline, left running (pid {pid})")
                kept[key] = pid
    finally:
        if not d.dry_run:  # also after a failed start, so what is running stays recorded
            kept.update({key: pid for key, pid in records.items() if key not in kept})
            pids_file.write_text("".join(f"{env} {service} {pid}\n" for (env, service), pid in kept.items()))
    d.say(f"pids file: {pids_file}")


# ── Baseline tag ─────────────────────────────────────────────────────────────
def set_baseline(d):
    if not d.dry_run:
        d.git("fetch", "--quiet", "--tags", "--force", "origin", "main")
    target = d.git("rev-parse", "--verify", f"{d.args.baseline_ref}^{{commit}}", check=False)
    _, current = remote_refs(d)
    if not target:
        d.warn(f"{d.args.baseline_ref} is not a commit here" + (" (a dry run does not fetch)" if d.dry_run else ""))
        return
    if current == target:
        d.say(f"{BASELINE_TAG} already points at {target[:7]}.")
        return
    if current and not d.args.force:
        d.warn(f"{BASELINE_TAG} points at {current[:7]}; pass --force to move it to {target[:7]}.")
        return
    subject = d.git("log", "-1", "--pretty=%s", target)
    if d.act_on(f"tag {target[:7]} ({subject}) as {BASELINE_TAG} and push the tag"):
        d.git("tag", "--force", BASELINE_TAG, target)
        d.git("push", "--quiet", *(["--force"] if current else []), "origin", f"refs/tags/{BASELINE_TAG}")
        d.link(BASELINE_TAG, d.github(f"/tree/{BASELINE_TAG}"))


BEATS = [
    dc.Beat("close-leftovers", "github", "Close pull requests and issues left open by earlier runs", close_leftovers),
    dc.Beat("revert-pr", "github", "Revert everything since demo-baseline in one pull request", revert_pr),
    dc.Beat("merge", "github", "Merge the reset pull request once its checks pass", merge),
    dc.Beat("apply-dev", "dispatch", "Apply dev", apply_dev),
    dc.Beat("apply-prod", "dispatch", "Apply prod through apply-prod and its approver", apply_prod),
    dc.Beat("seed-dashboard", "local", "Re-seed the Grid dispatch triage dashboard in dev", seed_dashboard),
    dc.Beat("traffic", "local", "Baseline traffic in dev and prod", traffic),
    dc.Beat("set-baseline", "github", f"Tag the {BASELINE_TAG} commit", set_baseline, on_demand=True),
]


if __name__ == "__main__":
    p = dc.parser(__doc__, BEATS)
    p.add_argument("--pids-file", default=str(REPO.parent / ".sessions/traffic/pids"),
                   help="traffic generator pid file (default: <repo parent>/.sessions/traffic/pids)")
    p.add_argument("--restart-traffic", action="store_true", help="restart every baseline generator")
    p.add_argument("--set-baseline", action="store_true", help=f"tag --baseline-ref as {BASELINE_TAG} and push it")
    p.add_argument("--baseline-ref", default="origin/main",
                   help="commit to tag with --set-baseline (default origin/main)")
    p.add_argument("--force", action="store_true", help=f"with --set-baseline, move an existing {BASELINE_TAG} tag")
    args = p.parse_args()
    if args.set_baseline:
        args.step = "set-baseline"
    dc.run_beats("Demo reset", BEATS, args)
    if not args.step and not args.dry_run:
        dc.mark("reset")  # the act drivers now ignore runs from before this point
        print(f"\nReset recorded in {dc.RESET_MARK}.")
