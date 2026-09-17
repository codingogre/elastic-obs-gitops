#!/usr/bin/env python3
"""Render a service catalog entry from an "Onboard a service" issue form.

Usage: onboard_service.py <issue-body-file> [--out-dir modules/bundle/catalog/services]

Prints the service name on stdout and writes <out-dir>/<name>.yaml. The form's field labels are the
section headings GitHub renders ("### Service name"). Values are checked here only for shape; the
bundle's variable validation is the policy that decides, so a bad target still surfaces in the PR plan.
"""
import argparse
import re
import sys
from pathlib import Path

FIELDS = {
    "Service name": "name",
    "Description": "description",
    "Owning team": "team",
    "Tier": "tier",
    "On-call contact email": "contact",
    "Runbook URL": "runbook_url",
    "Availability SLO target (%)": "availability_target",
    "Latency threshold (ms)": "latency_threshold_ms",
    "Latency SLO target (% of requests under the threshold)": "latency_target",
    "Release gate, maximum error ratio": "max_error_ratio",
    "Release gate, maximum p95 latency (ms)": "max_p95_ms",
}


def parse_form(body):
    values = {}
    for heading, content in re.findall(r"^###\s+(.+?)\s*\n(.*?)(?=^###\s|\Z)", body, flags=re.S | re.M):
        key = FIELDS.get(heading.strip())
        value = content.strip()
        if key and value and value != "_No response_":
            values[key] = value
    return values


def number(values, key):
    try:
        return float(values[key])
    except (KeyError, ValueError):
        sys.exit(f"onboard: '{key}' must be a number")


def fmt(n):
    return int(n) if float(n).is_integer() else n


def quote(text):
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render(v):
    lines = [
        f"name: {v['name']}",
        f"description: {quote(v['description'])}",
        f"team: {v['team']}",
        f"tier: {int(v['tier'])}",
        "contact:",
        f"  email: {v['contact']}",
    ]
    if v.get("runbook_url"):
        lines.append(f"runbook_url: {v['runbook_url']}")
    lines += [
        "slo:",
        f"  availability_target: {fmt(number(v, 'availability_target'))}",
        f"  latency_threshold_ms: {fmt(number(v, 'latency_threshold_ms'))}",
        f"  latency_target: {fmt(number(v, 'latency_target'))}",
        "  window: 7d",
        "release:",
        f"  max_error_ratio: {fmt(number(v, 'max_error_ratio'))}",
        f"  max_p95_ms: {fmt(number(v, 'max_p95_ms'))}",
    ]
    return "\n".join(lines) + "\n"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("body_file")
    p.add_argument("--out-dir", default="modules/bundle/catalog/services")
    args = p.parse_args()

    values = parse_form(Path(args.body_file).read_text())
    missing = [k for k in ("name", "description", "team", "tier", "contact") if k not in values]
    if missing:
        sys.exit(f"onboard: missing fields: {', '.join(missing)}")
    if not re.fullmatch(r"[a-z][a-z0-9-]{1,40}", values["name"]):
        sys.exit("onboard: service name must be lowercase letters, digits and hyphens")

    out = Path(args.out_dir) / f"{values['name']}.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(values))
    print(values["name"])


if __name__ == "__main__":
    main()
