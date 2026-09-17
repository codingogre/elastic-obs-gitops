"""Shared plumbing for the live-act drivers (scripts/demo_act1.py, demo_act2.py, demo_act3.py) and demo_reset.py.

A driver is a list of beats that run in order. Every driver takes:
  --step NAME          run one beat (on-demand beats run only this way)
  --skip A,B           leave beats out
  --pause              wait for Enter between beats
  --dry-run            print every action and link; dispatch, file, merge, start and stop nothing (reads still run)
  --no-elastic         skip Elastic reads; links still print
  --timeout SECONDS    how long one wait lasts before the beat moves on (default 900; Ctrl-C skips a wait)
  --since-minutes M    an earlier run of the same pipeline started this recently is reused (default 60)

Runs, pull requests and executions from before the last full demo reset (the time scripts/demo_reset.py writes to
<repo parent>/.sessions/demo-reset-at) are never reused, so a rehearsal's runs do not stand in for the live ones.

GitHub goes through the gh CLI, which must already be authenticated. Elastic reads use the credentials that
scripts/with_env.py reads (.env.dev and .env.prod beside the repo, or GITOPS_ENV_DIR) and never print them. Drivers
never write Elastic configuration: they dispatch pipelines, file issues, read, and run rules. Records in ServiceNow,
PagerDuty and Teams come only from Elastic connectors.
"""
import argparse
import contextlib
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kibana  # noqa: E402
import with_env  # noqa: E402

REPO = with_env.REPO
RESET_MARK = REPO.parent / ".sessions" / "demo-reset-at"
EPOCH = datetime.min.replace(tzinfo=timezone.utc)
ELASTIC_KEYS = ("KIBANA_ENDPOINT", "KIBANA_API_KEY", "KIBANA_SPACE", "ELASTICSEARCH_ENDPOINTS", "ELASTICSEARCH_API_KEY")
DEFAULT_SPACE = {"dev": "gitops-dev", "prod": "default"}
RUN_FIELDS = "databaseId,displayTitle,status,conclusion,createdAt,url,event,headSha"
PR_FIELDS = "number,title,url,state,headRefName,createdAt,mergedAt,mergeCommit"
# Step entries that wrap a step rather than being it (CAPABILITIES.md: take the last real entry per step).
WRAPPER_STEP_TYPES = ("step_level_timeout", "retry", "fallback")

# The application release the acts use (release-app.yml inputs).
SERVICE = "grid-dispatch"
BASELINE_VERSION = "2.4.3"
BAD_VERSION = "2.5.0"
LATENT_VERSION = "2.5.1"


class GhError(Exception):
    pass


@dataclass
class Beat:
    name: str
    kind: str  # dispatch | issue | read | manual | local
    title: str
    run: Callable
    on_demand: bool = False


def utcnow():
    return datetime.now(timezone.utc)


def parse_time(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00")) if text else None


def marked(name):
    """The time a driver recorded with mark(name), or None."""
    try:
        return parse_time((RESET_MARK.parent / f"demo-{name}-at").read_text().strip())
    except (OSError, ValueError):
        return None


def mark(name, when=None):
    """Record a time in <repo parent>/.sessions/demo-<name>-at, so a later run of a driver can read it."""
    path = RESET_MARK.parent / f"demo-{name}-at"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text((when or utcnow()).isoformat() + "\n")


def env_values(env):
    """One environment's Elastic settings from the files scripts/with_env.py reads (the process environment in CI)."""
    path = with_env.ENV_DIR / f".env.{env}"
    source = with_env.read_env_file(path) if path.is_file() else os.environ
    return {key: source.get(key) for key in ELASTIC_KEYS}


@contextlib.contextmanager
def elastic(env):
    """Point scripts/kibana.py at one environment for the duration of the block."""
    saved = {key: os.environ.get(key) for key in ELASTIC_KEYS}
    try:
        for key, value in env_values(env).items():
            if value:
                os.environ[key] = value
            else:
                os.environ.pop(key, None)
        os.environ.setdefault("KIBANA_SPACE", DEFAULT_SPACE[env])
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def step(execution, step_id):
    """The last real entry (status, output, error) for a step, from GET /api/workflows/executions/{id}."""
    entries = [s for s in (execution or {}).get("stepExecutions", [])
               if s.get("stepId") == step_id and s.get("stepType") not in WRAPPER_STEP_TYPES]
    return entries[-1] if entries else None


def parser(doc, beats):
    p = argparse.ArgumentParser(description=doc, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--step", choices=[b.name for b in beats], help="run only this beat")
    p.add_argument("--skip", type=lambda s: [x for x in s.split(",") if x], default=[],
                   help="comma-separated beats to leave out")
    p.add_argument("--pause", action="store_true", help="wait for Enter between beats")
    p.add_argument("--dry-run", action="store_true", help="print every action and link; change nothing")
    p.add_argument("--no-elastic", action="store_true", help="skip Elastic reads (links still print)")
    p.add_argument("--timeout", type=int, default=900, help="seconds one wait lasts (default 900)")
    p.add_argument("--since-minutes", type=int, default=60,
                   help="reuse a pipeline run started this recently instead of starting another (default 60)")
    return p


def add_release_args(p):
    p.add_argument("--degrade-after", type=int, default=180,
                   help=f"seconds before {SERVICE} {LATENT_VERSION} degrades; tune at rehearsal (default 180)")
    p.add_argument("--watch-minutes", type=int, default=30,
                   help=f"how long {LATENT_VERSION} keeps running after its gate passes, so the rollback has "
                        "something to stop (default 30)")


class Demo:
    def __init__(self, args):
        self.args = args
        self.dry_run = args.dry_run
        self.reset_at = marked("reset")
        self.since = max(utcnow() - timedelta(minutes=args.since_minutes), self.reset_at or EPOCH)
        self._repo = None
        self._elastic_down = set()

    # ── output ────────────────────────────────────────────────────────────────
    def say(self, text):
        print(f"  {text}", flush=True)

    def warn(self, text):
        print(f"  ! {text}", flush=True)

    def link(self, label, url):
        print(f"  {label + ':':<28} {url}", flush=True)

    def show_run(self, label, run):
        state = run["conclusion"] if run["status"] == "completed" else run["status"]
        self.link(label, f"{run['url']}  ({state})")

    def act_on(self, description):
        """True when an action should happen. A dry run prints it instead."""
        if self.dry_run:
            print(f"  [dry run] would {description}", flush=True)
            return False
        print(f"  -> {description}", flush=True)
        return True

    def enter(self, prompt):
        if self.dry_run:
            return
        try:
            input(f"  >> {prompt} ")
        except EOFError:
            print()
        except KeyboardInterrupt:
            print()
            sys.exit(130)

    def manual(self, instructions, links=()):
        """A beat a person does in a browser: print the links and steps, then wait for Enter."""
        for label, url in links:
            self.link(label, url)
        for line in instructions:
            self.say(line if line.startswith(" ") else f"- {line}")
        self.enter("Press Enter when done")

    def wait_for(self, what, check, timeout=None, interval=10, env=None):
        """Poll check() until it returns something truthy. A dry run checks once. Ctrl-C stops waiting."""
        result = check()
        if result or (env and not self.elastic_ok(env)):
            return result
        if self.dry_run:
            self.say(f"[dry run] would wait for {what}")
            return None
        deadline = time.monotonic() + (timeout or self.args.timeout)
        print(f"  ... waiting for {what} (Ctrl-C skips)", end="", flush=True)
        try:
            while time.monotonic() < deadline:
                time.sleep(interval)
                result = check()
                if result:
                    print(" done", flush=True)
                    return result
                if env and not self.elastic_ok(env):
                    print(" stopped", flush=True)
                    return None
                print(".", end="", flush=True)
        except KeyboardInterrupt:
            print(" skipped", flush=True)
            return None
        print(" timed out", flush=True)
        return None

    # ── GitHub ────────────────────────────────────────────────────────────────
    def gh(self, *argv, parse=True, ok_codes=(0,), input_text=None):
        result = subprocess.run(["gh", *argv], cwd=REPO, text=True, capture_output=True, input=input_text)
        if result.returncode not in ok_codes:
            raise GhError(f"gh {' '.join(argv[:2])}: {(result.stderr or result.stdout).strip()[:300]}")
        out = result.stdout.strip()
        return (json.loads(out) if out else None) if parse else out

    def git(self, *argv, check=True):
        result = subprocess.run(["git", *argv], cwd=REPO, text=True, capture_output=True)
        if check and result.returncode != 0:
            raise GhError(f"git {' '.join(argv[:2])}: {(result.stderr or result.stdout).strip()[:300]}")
        return result.stdout.strip()

    @property
    def repo(self):
        if not self._repo:
            self._repo = self.gh("repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner", parse=False)
        return self._repo

    def github(self, path=""):
        return f"https://github.com/{self.repo}{path}"

    def actions(self, workflow):
        return self.github(f"/actions/workflows/{workflow}")

    def prs(self, state="open", label=None, head=None, limit=30):
        argv = ["pr", "list", "--state", state, "--limit", str(limit), "--json", PR_FIELDS]
        argv += ["--label", label] if label else []
        argv += ["--head", head] if head else []
        return self.gh(*argv) or []

    def pr(self, number):
        return self.gh("pr", "view", str(number), "--json", PR_FIELDS + ",comments")

    def pr_checks(self, number):
        """Check runs on a pull request. gh exits 8 while checks are pending and 1 when one failed."""
        try:
            return self.gh("pr", "checks", str(number), "--json", "name,bucket,state,link,workflow",
                           ok_codes=(0, 1, 8)) or []
        except (GhError, json.JSONDecodeError):
            return []

    def comment_with_marker(self, pr, marker):
        """Body of the sticky comment scripts/pr_comment.py wrote for a job, or None."""
        tag = f"<!-- gitops:{marker} -->"
        bodies = [c.get("body") or "" for c in (pr.get("comments") or [])]
        found = [b for b in bodies if tag in b]
        return found[-1].replace(tag, "").strip() if found else None

    def runs(self, workflow, event=None, limit=20):
        argv = ["run", "list", "--workflow", workflow, "--limit", str(limit), "--json", RUN_FIELDS]
        argv += ["--event", event] if event else []
        return self.gh(*argv) or []

    def run_view(self, run_id):
        return self.gh("run", "view", str(run_id), "--json", RUN_FIELDS)

    def find_run(self, workflow, title=None, event=None, head_sha=None, since=None, after=None):
        """The newest run still going, or else the newest started since `since`. Skipped runs and runs from before
        the last demo reset never count; `after` also drops runs created before it, whatever their status."""
        since = since or self.since
        after = max(after or EPOCH, self.reset_at or EPOCH)
        runs = [r for r in self.runs(workflow, event)
                if r.get("conclusion") != "skipped"
                and (title is None or r["displayTitle"] == title)
                and (head_sha is None or r["headSha"] == head_sha)
                and parse_time(r["createdAt"]) >= after]
        going = [r for r in runs if r["status"] != "completed"]
        recent = [r for r in runs if parse_time(r["createdAt"]) >= since]
        return (going or recent or [None])[0]

    def dispatch(self, workflow, fields=None, title=None):
        """Start a workflow_dispatch run on main and return it once GitHub lists it (None in a dry run)."""
        fields = fields or {}
        shown = " ".join(f"{k}={v}" for k, v in fields.items())
        if not self.act_on(f"dispatch {workflow}" + (f" ({shown})" if shown else "")):
            return None
        started = utcnow() - timedelta(seconds=30)
        argv = ["workflow", "run", workflow, "--ref", "main"]
        for key, value in fields.items():
            argv += ["-f", f"{key}={value}"]
        out = self.gh(*argv, parse=False)
        match = re.search(r"/actions/runs/(\d+)", out)
        run_id = match.group(1) if match else None

        def listed():
            for run in self.runs(workflow, "workflow_dispatch", limit=10):
                if run_id and str(run["databaseId"]) == run_id:
                    return run
                if not run_id and parse_time(run["createdAt"]) >= started and title in (None, run["displayTitle"]):
                    return run
            return None

        return self.wait_for(f"GitHub to list the {workflow} run", listed, timeout=120, interval=3)

    def wait_run(self, run, what, until="completed", timeout=None):
        """Refresh a run until it completes, or with until='started' until it is past queueing and approval."""
        if not run:
            return None
        waiting = ("queued", "waiting", "pending", "requested", "action_required")

        def check():
            fresh = self.run_view(run["databaseId"])
            if until == "completed":
                return fresh if fresh["status"] == "completed" else None
            return fresh if fresh["status"] not in waiting else None

        return self.wait_for(what, check, timeout) or run

    def wait_merged(self, number, what):
        def merged():
            pr = self.gh("pr", "view", str(number), "--json", PR_FIELDS)
            return pr if pr.get("mergedAt") else None

        return self.wait_for(what, merged, interval=5)

    def push_run(self, workflow, sha, wait_seconds=60):
        """The run a push to main started for `sha` (skipped runs ignored), waiting briefly for GitHub to list it."""
        return self.wait_for(f"{workflow} to start for {sha[:7]}",
                             lambda: self.find_run(workflow, event="push", head_sha=sha, since=EPOCH),
                             timeout=wait_seconds, interval=5)

    # ── Elastic ───────────────────────────────────────────────────────────────
    def kibana_link(self, env, path):
        with elastic(env):
            try:
                return kibana.kibana_url(path)
            except KeyError:
                space = os.environ.get("KIBANA_SPACE", DEFAULT_SPACE[env])
                return f"<{env} Kibana>" + (path if space == "default" else f"/s/{space}{path}")

    def elastic_ok(self, env):
        return not self.args.no_elastic and env not in self._elastic_down

    def elastic_call(self, env, what, fn, missing=None):
        """Run one Elastic call (a read, or running a rule) in env. Returns fn()'s result, `missing` on HTTP 404, and
        None when calls are off or fail. Rejected or absent credentials switch that environment off with one message."""
        if not self.elastic_ok(env):
            return None
        try:
            with elastic(env):
                return fn()
        except kibana.HTTPError as e:
            if e.status == 404:
                return missing
            if e.status in (401, 403):
                self._elastic_down.add(env)
                self.warn(f"{env} Elastic rejected the API key (HTTP {e.status}); skipping {env} Elastic calls. "
                          f"Links still work; check the key in .env.{env}.")
            else:
                self.warn(f"{env}: {what} failed with HTTP {e.status}")
        except KeyError as e:
            self._elastic_down.add(env)
            self.warn(f"no {env} credentials ({e.args[0]} is not set); skipping {env} Elastic calls")
        except (OSError, TimeoutError, ValueError) as e:
            self.warn(f"{env}: {what} failed ({type(e).__name__})")
        return None

    def executions(self, env, workflow_id, size=10):
        """Newest first: id, status, startedAt. None when Elastic calls are off."""
        path = f"/api/workflows/workflow/{workflow_id}/executions?size={size}"
        body = self.elastic_call(env, f"listing {workflow_id} executions", lambda: kibana.kibana("GET", path),
                                 missing={"results": []})
        if body is None:
            return None
        return sorted(body.get("results") or [], key=lambda e: e.get("startedAt") or "", reverse=True)

    def execution(self, env, execution_id, outputs=True):
        query = "?includeOutput=true" if outputs else ""
        return self.elastic_call(env, "reading a workflow execution",
                                 lambda: kibana.kibana("GET", f"/api/workflows/executions/{execution_id}{query}"))

    def execution_link(self, env, workflow_id, execution_id=None):
        return self.kibana_link(env, f"/app/workflows/{workflow_id}?tab=executions"
                                     + (f"&executionId={execution_id}" if execution_id else ""))

    def slo_target(self, env, slo_id):
        """The SLO objective as a percentage, False when the SLO does not exist, None when unreadable."""
        slo = self.elastic_call(env, f"reading SLO {slo_id}",
                                lambda: kibana.kibana("GET", f"/api/observability/slos/{slo_id}"), missing=False)
        if not slo:
            return slo
        return round(float(slo["objective"]["target"]) * 100, 3)


def start_release(d, version, error_rate, degrade_after=0, watch_minutes=None, env="prod"):
    """Find or dispatch one release-app run; its run name is 'release <service> <version> to <env>'."""
    title = f"release {SERVICE} {version} to {env}"
    run = d.find_run("release-app.yml", title=title)
    if run:
        d.say(f"Reusing the {title} run (started {run['createdAt']}).")
    else:
        fields = {"service": SERVICE, "version": version, "baseline": BASELINE_VERSION, "env": env,
                  "error_rate": error_rate, "degrade_after": degrade_after}
        if watch_minutes:
            fields["watch_minutes"] = watch_minutes
        run = d.dispatch("release-app.yml", fields, title=title)
    if run:
        d.show_run("release-app run", run)
    else:
        d.link("release-app runs", d.actions("release-app.yml"))
    return run


def start_latent_bug(d):
    d.say(f"{SERVICE} {LATENT_VERSION} passes its gate, then degrades after {d.args.degrade_after}s, "
          "so its alert lands during Act 3.")
    return start_release(d, LATENT_VERSION, "0.005", d.args.degrade_after, d.args.watch_minutes)


def prod_live(d):
    """True when the repository variable PROD_LIVE lets a merge to main apply prod by itself."""
    try:
        variables = d.gh("variable", "list", "--json", "name,value") or []
    except GhError:
        return False
    return any(v["name"] == "PROD_LIVE" and v["value"] == "true" for v in variables)


def apply_prod_run(d, merged):
    """The apply-prod run for a merged pull request: the push run when PROD_LIVE is "true" (otherwise that run is
    skipped), else a workflow_dispatch run, started here if there is none yet. Prod still waits for its approver."""
    live = prod_live(d)
    after = parse_time(merged["mergedAt"]) - timedelta(seconds=30)
    run = d.find_run("apply-prod.yml", event="push" if live else "workflow_dispatch", after=after)
    if not run and live:
        run = d.push_run("apply-prod.yml", merged["mergeCommit"]["oid"])
    return run or d.dispatch("apply-prod.yml")


def run_beats(title, beats, args):
    """Run the selected beats in order."""
    unknown = [s for s in args.skip if s not in {b.name for b in beats}]
    if unknown:
        sys.exit(f"unknown beat in --skip: {', '.join(unknown)}; beats: {', '.join(b.name for b in beats)}")
    d = Demo(args)
    selected = [b for b in beats if (b.name == args.step if args.step else not b.on_demand) and b.name not in args.skip]
    note = "  [dry run: nothing is dispatched, filed, merged, started or stopped]" if d.dry_run else ""
    print(title + note, flush=True)
    for i, beat in enumerate(selected, 1):
        if args.pause and i > 1:
            d.enter(f"Enter for {beat.name}: {beat.title}")
        print(f"\n-- {i}/{len(selected)}  {beat.name} ({beat.kind})  {beat.title}", flush=True)
        try:
            beat.run(d)
        except (GhError, kibana.HTTPError) as e:
            d.warn(f"{beat.name} stopped: {e}")
        except KeyboardInterrupt:
            print()
            sys.exit(130)
    return d
