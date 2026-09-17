#!/usr/bin/env python3
"""Act 3, automate: prod protects itself. A latent bug is remediated with a human approval; a hand edit is reverted.

Usage: python3 scripts/demo_act3.py [--pause] [--dry-run] [--step NAME] [--degrade-after 180]
       make demo-act3 [PAUSE=1] [STEP=drift|latent-bug|run-rule] [DRY_RUN=1]

Beats, in order (kind in brackets):
  latent-bug          [dispatch]  grid-dispatch 2.5.1 in prod (normally started at the end of Act 2; found, not re-run)
  dashboard-refused   [manual]    as the operator user, try to edit the golden signals dashboard in prod: refused
  slo-edit            [manual]    as the operator user, loosen svc-grid-dispatch-availability 99.5 -> 95; reads it back
                                  and records when it was saved
  drift               [dispatch]  run drift-prod (a run created before the edit is never reused)
  episode             [read]      the error-spike episode and its remediate-service execution
  triage              [read]      the SRE agent's likely cause, confidence and recommendation
  response            [read]      ServiceNow incident, PagerDuty page and the approval card, from the execution steps
  approve             [manual]    approve in the Kibana execution view; follows rollback-app
  recovery            [read]      the recovery run closes the incident and the page and posts the all-clear
  drift-result        [read]      drift-prod finished: SLO back at 99.5, the "Drift reverted" issue
  run-rule            [dispatch]  on demand: run the error-spike rule now instead of waiting for its schedule

Every beat is safe to re-run: it finds the run, execution or issue it made before. Common options are described in
scripts/demo_common.py.
"""
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import demo_common as dc  # noqa: E402
import kibana  # noqa: E402

SLO_ID = f"svc-{dc.SERVICE}-availability"
RULE_ID = f"svc-{dc.SERVICE}-error-spike"
DASHBOARD_ID = f"svc-{dc.SERVICE}-golden-signals"
REMEDIATE = "gitops-remediate-service"
DRIFT_ISSUE = f"Drift reverted: {SLO_ID}"  # scripts/drift.py report
TERMINAL = ("completed", "failed", "cancelled", "timed_out", "skipped")
EDIT_MARK = "slo-edit"  # dc.mark name: when the prod SLO edit was saved
# A drift-prod run queued this long before the edit still plans after it: checkout, provider build and init come first.
EDIT_SLACK = timedelta(seconds=30)


def latent_run(d):
    return d.find_run("release-app.yml", title=f"release {dc.SERVICE} {dc.LATENT_VERSION} to prod")


def remediations(d, status, episode_id=None):
    """Remediation executions in prod since the latent release started, newest first, as (id, startedAt, episode)."""
    started = latent_run(d)
    after = dc.parse_time(started["createdAt"]) if started else d.since
    found = []
    for item in d.executions("prod", REMEDIATE, size=10) or []:
        started_at = dc.parse_time(item.get("startedAt"))
        if item.get("status") == "skipped" or not started_at or started_at < after:
            continue
        full = d.execution("prod", item["id"], outputs=False) or {}
        episodes = (((full.get("context") or {}).get("inputs") or {}).get("payload") or {}).get("episodes") or [{}]
        episode = episodes[0]
        if episode.get("episode_status") != status or (episode_id and episode.get("episode_id") != episode_id):
            continue
        if status == "active" and (episode.get("data") or {}).get("service") not in (None, dc.SERVICE):
            continue
        found.append((item["id"], item.get("startedAt"), episode))
    return found


def active(d):
    return next(iter(remediations(d, "active")), None)


def failed(run):
    return run["status"] == "completed" and run["conclusion"] != "success"


def drift_runs(d):
    """drift-prod runs created after the SLO edit in this session, oldest first: the first to plan reverts the edit."""
    edited = dc.marked(EDIT_MARK)
    if not edited or edited < d.since:
        return []
    return sorted((r for r in d.runs("drift-prod.yml") if dc.parse_time(r["createdAt"]) >= edited
                   and r.get("conclusion") not in ("skipped", "cancelled")), key=lambda r: r["createdAt"])


def execution_until(d, execution_id, what, done):
    """Wait until done(execution) holds for the execution with step outputs; returns the latest read."""
    latest = {}

    def check():
        latest["execution"] = d.execution("prod", execution_id)
        return latest["execution"] if latest["execution"] and done(latest["execution"]) else None

    return d.wait_for(what, check, interval=10, env="prod") or latest.get("execution")


def latent_bug(d):
    dc.start_latent_bug(d)


def dashboard_refused(d):
    d.manual(["Signed in to prod Kibana as the demo operator user (read-only dashboards role), open the dashboard.",
              "Edit is refused: dashboards in prod belong to the pipeline."],
             links=[("Grid dispatch golden signals", d.kibana_link("prod", f"/app/dashboards#/view/{DASHBOARD_ID}"))])


def slo_edit(d):
    before = d.slo_target("prod", SLO_ID)
    if before is False:
        d.warn(f"{SLO_ID} is not in prod yet: finish apply-prod in Act 2 first.")
    elif before is not None:
        d.say(f"{SLO_ID} target in prod now: {before}%")
    d.manual(["Still as the operator user: Edit, target 99.5 -> 95, Save.",
              "Then Enter: the next beat starts drift-prod."],
             links=[("Edit the SLO", d.kibana_link("prod", f"/app/slos/edit/{SLO_ID}")),
                    ("SLO", d.kibana_link("prod", f"/app/slos/{SLO_ID}"))])
    if not d.dry_run:
        dc.mark(EDIT_MARK, dc.utcnow() - EDIT_SLACK)
    after = None if d.dry_run else d.slo_target("prod", SLO_ID)
    if after not in (None, False):
        d.say(f"{SLO_ID} target in prod: {after}%")
        if after == before:
            d.warn("The target did not change; drift-prod will find nothing to revert.")


def drift(d):
    busy = [r for r in d.runs("apply-prod.yml", limit=5) if r["status"] != "completed"]
    if busy:
        d.warn("apply-prod is still going; drift-prod shares its tf-prod lock and queues behind it.")
        d.show_run("apply-prod run", busy[0])
    run = next((r for r in drift_runs(d) if not failed(r)), None)
    if run:
        d.say("Reusing the drift-prod run started after the SLO edit.")
    else:
        if not d.dry_run and (dc.marked(EDIT_MARK) or dc.EPOCH) < d.since:
            dc.mark(EDIT_MARK, dc.utcnow() - EDIT_SLACK)  # slo-edit was skipped: the edit is saved by now
        run = d.dispatch("drift-prod.yml")
    if run:
        d.show_run("drift-prod run", run)
    d.link("drift-prod runs", d.actions("drift-prod.yml"))


def episode(d):
    started = latent_run(d)
    if started:
        d.show_run("release 2.5.1 run", started)
    else:
        d.warn(f"No {dc.SERVICE} {dc.LATENT_VERSION} release in this session. Run make demo-act3 STEP=latent-bug.")
    d.link("Alert episodes", d.kibana_link("prod", "/app/management/alertingV2/episodes"))
    found = d.wait_for("the error-spike episode to reach remediate-service", lambda: active(d), interval=15, env="prod")
    if not found:
        d.say("No episode yet: make demo-act3 STEP=run-rule runs the rule now.")
        d.link("Remediation runs", d.execution_link("prod", REMEDIATE))
        return
    execution_id, _, ep = found
    data = ep.get("data") or {}
    d.say(f"Episode active: {data.get('service', dc.SERVICE)} {data.get('version', '')}, "
          f"error ratio {data.get('error_ratio', '?')}")
    d.link("Episode", d.kibana_link("prod", f"/app/management/alertingV2/episodes/{ep.get('episode_id')}"))
    d.link("Remediation run", d.execution_link("prod", REMEDIATE, execution_id))


def triage(d):
    found = active(d)
    if not found:
        d.warn("No active remediation run yet. Run make demo-act3 STEP=episode.")
        return
    execution_id = found[0]
    execution = execution_until(
        d, execution_id, "the SRE agent's triage",
        lambda e: (dc.step(e, "triage") or {}).get("output") or e.get("status") in TERMINAL + ("waiting_for_input",))
    answer = ((dc.step(execution, "triage") or {}).get("output") or {}).get("structured_output") or {}
    for key in ("likely_cause", "confidence", "recommendation", "summary"):
        if answer.get(key):
            d.say(f"{key.replace('_', ' ').capitalize()}: {str(answer[key])[:300]}")
    if not answer:
        d.say("No structured answer (yet); the workflow falls back to a summary from the alert.")
    d.link("Remediation run", d.execution_link("prod", REMEDIATE, execution_id))


def response(d):
    found = active(d)
    if not found:
        d.warn("No active remediation run yet. Run make demo-act3 STEP=episode.")
        return
    execution_id = found[0]
    execution = execution_until(d, execution_id, "the approval request",
                                lambda e: e.get("status") in TERMINAL + ("waiting_for_input",))
    servicenow = dc.step(execution, "servicenow_open") or {}
    incident = servicenow.get("output") or {}
    d.say(f"ServiceNow: {incident.get('title') or servicenow.get('status', 'not reached')}")
    if incident.get("url"):
        d.link("ServiceNow incident", incident["url"])
    pagerduty = dc.step(execution, "pagerduty_trigger") or {}
    dedup_key = (pagerduty.get("output") or {}).get("dedup_key")
    d.say(f"PagerDuty: {pagerduty.get('status', 'not reached')}" + (f" (dedup key {dedup_key})" if dedup_key else ""))
    card = dc.step(execution, "teams_approval") or {}
    d.say(f'Teams "Approve rollback" card: {card.get("status", "not reached")}')
    d.say(f"Remediation run: {(execution or {}).get('status', 'unknown')}")
    d.link("Remediation run", d.execution_link("prod", REMEDIATE, execution_id))


def approve(d):
    found = active(d)
    if not found:
        d.warn("No active remediation run yet. Run make demo-act3 STEP=episode.")
        d.link("Remediation runs", d.execution_link("prod", REMEDIATE))
        return
    execution_id, started_at, _ = found
    status = (d.execution("prod", execution_id, outputs=False) or {}).get("status")
    if status not in TERMINAL:
        d.manual(['Teams card "Approve rollback" opens the waiting run in Kibana (or use the link).',
                  "Approve the waiting step."],
                 links=[("Waiting remediation run", d.execution_link("prod", REMEDIATE, execution_id))])
    else:
        d.say(f"The remediation run is already {status}.")
    execution = execution_until(d, execution_id, "the approval to be recorded",
                                lambda e: e.get("status") != "waiting_for_input")
    decision = ((dc.step(execution, "approve_rollback") or {}).get("output") or {}).get("response") or {}
    if "approved" in decision:
        d.say(f"Approved: {decision['approved']}")
    after = dc.parse_time(started_at)
    rollback = d.wait_for("rollback-app to start",
                          lambda: d.find_run("rollback-app.yml", event="repository_dispatch", after=after),
                          timeout=180, interval=5)
    if rollback:
        d.show_run("rollback-app run", rollback)
        d.show_run("rollback-app run", d.wait_run(rollback, "rollback-app to finish"))
    else:
        d.link("rollback-app runs", d.actions("rollback-app.yml"))
    release = latent_run(d)
    if release:
        d.show_run("release 2.5.1 run", release)


def recovery(d):
    found = active(d)
    if not found:
        d.warn("No active remediation run to follow. Run make demo-act3 STEP=episode.")
        return
    episode_id = found[2].get("episode_id")
    closed = d.wait_for("the episode to recover (the release has to stop first)",
                        lambda: next(iter(remediations(d, "inactive", episode_id)), None), interval=15, env="prod")
    if not closed:
        d.link("Remediation runs", d.execution_link("prod", REMEDIATE))
        return
    execution = execution_until(d, closed[0], "the recovery run to finish", lambda e: e.get("status") in TERMINAL)
    servicenow = dc.step(execution, "servicenow_close") or {}
    d.say(f"ServiceNow: {(servicenow.get('output') or {}).get('title', '')} {servicenow.get('status', 'not reached')}")
    d.say(f"PagerDuty resolve: {(dc.step(execution, 'pagerduty_resolve') or {}).get('status', 'not reached')}")
    d.say(f'Teams "All clear": {(dc.step(execution, "teams_all_clear") or {}).get("status", "not reached")}')
    d.link("Recovery run", d.execution_link("prod", REMEDIATE, closed[0]))
    d.link("Episode", d.kibana_link("prod", f"/app/management/alertingV2/episodes/{episode_id}"))


def drift_result(d):
    runs = drift_runs(d)
    run = next((r for r in runs if not failed(r)), runs[-1] if runs else None)
    if not run:
        d.warn("No drift-prod run since the SLO edit. Run make demo-act3 STEP=drift.")
        return
    if run["status"] != "completed":
        run = d.wait_run(run, "drift-prod to finish")
    d.show_run("drift-prod run", run)
    target = d.slo_target("prod", SLO_ID)
    if target not in (None, False):
        d.say(f"{SLO_ID} target in prod: {target}%")
    issues = d.gh("issue", "list", "--label", "drift", "--state", "open", "--search", f'"{DRIFT_ISSUE}" in:title',
                  "--json", "number,title,url") or []
    issue = next((i for i in issues if i["title"] == DRIFT_ISSUE), None)
    if issue:
        d.link("Drift issue", issue["url"])
    else:
        d.link("Drift issues", d.github("/issues?q=is%3Aissue+label%3Adrift"))
    d.say('Teams: the "Drift reverted" card.')


def run_rule(d):
    d.say("Evaluates the error-spike rule now; it changes no configuration.")
    if d.act_on(f"run the Alerting v2 rule {RULE_ID} in prod"):
        if d.elastic_call("prod", f"running {RULE_ID}",
                          lambda: kibana.kibana("POST", f"/api/alerting/v2/rules/{RULE_ID}/_run") or True):
            d.say("Rule run requested.")
    d.link("Alert episodes", d.kibana_link("prod", "/app/management/alertingV2/episodes"))


BEATS = [
    dc.Beat("latent-bug", "dispatch", "grid-dispatch 2.5.1 is running in prod", latent_bug),
    dc.Beat("dashboard-refused", "manual", "A prod dashboard edit is refused", dashboard_refused),
    dc.Beat("slo-edit", "manual", "Loosen the prod SLO by hand", slo_edit),
    dc.Beat("drift", "dispatch", "Start drift-prod", drift),
    dc.Beat("episode", "read", "Latent bug caught: episode and remediation run", episode),
    dc.Beat("triage", "read", "The SRE agent names the cause", triage),
    dc.Beat("response", "read", "ServiceNow, PagerDuty and the approval card", response),
    dc.Beat("approve", "manual", "A person approves; rollback-app runs", approve),
    dc.Beat("recovery", "read", "Recovery closes everything", recovery),
    dc.Beat("drift-result", "read", "The loosened SLO is put back", drift_result),
    dc.Beat("run-rule", "dispatch", "Fallback: run the error-spike rule now", run_rule, on_demand=True),
]


if __name__ == "__main__":
    p = dc.parser(__doc__, BEATS)
    dc.add_release_args(p)
    dc.run_beats("Act 3: automate (prod)", BEATS, p.parse_args())
