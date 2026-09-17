#!/usr/bin/env python3
"""Summarize `terraform show -json <plan>` as redacted Markdown, safe to post on a PR or send to an AI reviewer.

Usage: plan_summary.py plan.json [--title TEXT] [--max-chars N] [--format markdown|json]

Only resource changes are read. Every value marked in before_sensitive/after_sensitive is replaced with
"(sensitive)" before anything is printed; the plan's `variables` and `configuration` sections, which can
hold sensitive values in clear text, are never read. Write-only arguments never appear in plan JSON.
"""
import argparse
import json
import sys

SENSITIVE = "(sensitive)"
SYMBOL = {"create": "+", "update": "~", "delete": "-", "replace": "-/+", "read": "<=", "import": "->", "no-op": " "}


def redact(value, mask):
    if mask is True:
        return SENSITIVE
    if isinstance(value, dict):
        return {k: redact(v, mask.get(k, False) if isinstance(mask, dict) else False) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, mask[i] if isinstance(mask, list) and i < len(mask) else False) for i, v in enumerate(value)]
    return value


def maybe_json(value):
    if isinstance(value, str) and value[:1] in "{[":
        try:
            return json.loads(value)
        except ValueError:
            pass
    return value


def diff(before, after, path=""):
    """Yield (path, before, after) for every leaf that differs, descending into JSON-encoded strings."""
    before, after = maybe_json(before), maybe_json(after)
    if isinstance(before, dict) and isinstance(after, dict):
        for key in sorted(set(before) | set(after)):
            yield from diff(before.get(key), after.get(key), f"{path}.{key}" if path else key)
    elif isinstance(before, list) and isinstance(after, list) and len(before) == len(after):
        for i, (b, a) in enumerate(zip(before, after)):
            yield from diff(b, a, f"{path}[{i}]")
    elif before != after:
        yield path, before, after


def short(value, limit=100):
    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else json.dumps(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def action_of(change):
    actions = change["actions"]
    if actions == ["delete", "create"] or actions == ["create", "delete"]:
        return "replace"
    if actions == ["no-op"] and change.get("importing"):
        return "import"
    return actions[0]


def summarize(plan):
    rows = []
    for rc in plan.get("resource_changes", []):
        change = rc["change"]
        action = action_of(change)
        if action in ("no-op", "read"):
            continue
        before = redact(change.get("before"), change.get("before_sensitive", False))
        after = redact(change.get("after"), change.get("after_sensitive", False))
        changed = []
        if action in ("update", "replace"):
            changed = [(p, b, a) for p, b, a in diff(before, after)]
        elif action == "create":
            changed = [(k, None, v) for k, v in sorted((after or {}).items()) if v not in (None, [], {}, "")]
        rows.append({
            "address": rc["address"],
            "action": action,
            "importing": bool(change.get("importing")),
            "replace_paths": change.get("replace_paths"),
            "changes": [{"path": p, "before": b, "after": a} for p, b, a in changed],
        })
    return rows


def to_markdown(rows, title, max_chars):
    counts = {}
    for r in rows:
        counts[r["action"]] = counts.get(r["action"], 0) + 1
    order = ["import", "create", "update", "replace", "delete"]
    headline = ", ".join(f"{counts[a]} to {a}" for a in order if a in counts) or "no changes"
    out = [f"### {title}", "", f"**{headline}**", ""]
    for r in rows:
        extra = " (import)" if r["importing"] and r["action"] != "import" else ""
        out.append(f"<details><summary><code>{SYMBOL.get(r['action'], '?')} {r['address']}</code>{extra}</summary>\n")
        for c in r["changes"][:40]:
            if r["action"] == "create":
                out.append(f"- `{c['path']}` = `{short(c['after'])}`")
            else:
                out.append(f"- `{c['path']}`: `{short(c['before'])}` → `{short(c['after'])}`")
        if len(r["changes"]) > 40:
            out.append(f"- … {len(r['changes']) - 40} more")
        out.append("\n</details>")
    text = "\n".join(out)
    if len(text) > max_chars:
        text = text[: max_chars - 60] + "\n\n… truncated; see the job log for the full plan."
    return text + "\n"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("plan_json")
    p.add_argument("--title", default="Terraform plan")
    p.add_argument("--max-chars", type=int, default=60000)
    p.add_argument("--format", choices=["markdown", "json"], default="markdown")
    args = p.parse_args()
    with open(args.plan_json) as f:
        rows = summarize(json.load(f))
    if args.format == "json":
        json.dump(rows, sys.stdout, indent=1, default=str)
    else:
        sys.stdout.write(to_markdown(rows, args.title, args.max_chars))


if __name__ == "__main__":
    main()
