#!/usr/bin/env python3
"""Evaluate a release gate inside Elastic and turn the verdict into an exit code.

Usage:
  gate.py --service grid-dispatch --version 2.5.0 [--baseline 2.4.3] [--mode app|config] [--window 10m]
          [--notify fail|always|never] [--environment dev|prod] [--warn-exit 0]

Runs the gitops-release-gate workflow for gate-<service> in the environment's Kibana space, waits for it, prints
the verdict and reasons, appends them to the GitHub job summary, and exits 0 on pass, 1 on fail and --warn-exit
(default 2) on warn. The objectives are not passed in: they live in the elasticgitops_release_gate resource.
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kibana  # noqa: E402

WORKFLOW_ID = "gitops-release-gate"


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--service", required=True)
    p.add_argument("--version", required=True)
    p.add_argument("--baseline", default="")
    p.add_argument("--mode", choices=["app", "config"], default="app")
    p.add_argument("--window", default="10m")
    p.add_argument("--notify", choices=["fail", "always", "never"], default="fail")
    p.add_argument("--environment", default=os.environ.get("GITOPS_ENV", ""))
    p.add_argument("--warn-exit", type=int, default=2)
    p.add_argument("--timeout", type=int, default=900)
    args = p.parse_args()

    run_url = ""
    if os.environ.get("GITHUB_ACTIONS") == "true":
        run_url = f"{os.environ['GITHUB_SERVER_URL']}/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{os.environ['GITHUB_RUN_ID']}"

    inputs = {
        "gate_id": f"gate-{args.service}",
        "mode": args.mode,
        "service": args.service,
        "version": args.version,
        "baseline_version": args.baseline,
        "window": args.window,
        "environment": args.environment,
        "notify": args.notify,
        "run_url": run_url,
    }
    print(f"gate: {args.mode} gate for {args.service} {args.version}"
          + (f" against {args.baseline}" if args.baseline else "") + f" over {args.window}")
    try:
        execution = kibana.run_workflow(WORKFLOW_ID, inputs, timeout_s=args.timeout)
    except Exception as e:  # the gate must never pass by accident
        print(f"gate: could not evaluate: {e}")
        sys.exit(1)

    output = (execution.get("context") or {}).get("output") or {}
    verdict = output.get("verdict") or ("fail" if execution.get("status") != "completed" else "warn")
    reasons = output.get("reasons") or []
    if isinstance(reasons, str):
        reasons = [reasons]
    if execution.get("status") != "completed":
        reasons = reasons or [f"The gate workflow ended with status {execution.get('status')}."]

    # Endpoints stay out of public logs and job summaries: name the run, don't link the host.
    where = f"Kibana → Workflows → {WORKFLOW_ID} → execution {execution['id']}"
    print(f"gate: verdict {verdict.upper()}")
    for reason in reasons:
        print(f"  - {reason}")
    if output.get("explanation"):
        print(f"gate: explanation\n{output['explanation']}")

    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_file:
        icon = {"pass": "✅", "warn": "⚠️", "fail": "❌"}.get(verdict, "❔")
        lines = [f"### {icon} Release gate: {verdict.upper()}", "",
                 f"`{args.service}` **{args.version}**" + (f" against {args.baseline}" if args.baseline else "")
                 + f" ({args.mode} mode, {args.window} window)", ""]
        lines += [f"- {r}" for r in reasons]
        numbers = {k: output[k] for k in ("error_ratio", "p95_ms", "requests", "baseline_error_ratio", "baseline_p95_ms")
                   if k in output}
        if numbers:
            lines += ["", "```json", json.dumps(numbers, indent=1), "```"]
        if output.get("explanation"):
            lines += ["", "**Why, in plain English**", "", str(output["explanation"])]
        lines += ["", f"Details: {where}"]
        with open(summary_file, "a") as f:
            f.write("\n".join(lines) + "\n")

    sys.exit({"pass": 0, "fail": 1}.get(verdict, args.warn_exit))


if __name__ == "__main__":
    main()
