#!/usr/bin/env python3
"""Create or update one sticky pull request comment per job, found by a hidden marker.

Usage: pr_comment.py --pr 12 --marker dev-plan --body-file plan.md
Uses the gh CLI (GH_TOKEN) and GITHUB_REPOSITORY.
"""
import argparse
import json
import os
import subprocess


def gh_api(*args, body=None):
    cmd = ["gh", "api", *args]
    result = subprocess.run(cmd, input=json.dumps(body) if body is not None else None, text=True,
                            capture_output=True, check=True)
    return json.loads(result.stdout) if result.stdout.strip() else None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--pr", required=True)
    p.add_argument("--marker", required=True)
    p.add_argument("--body-file", required=True)
    args = p.parse_args()

    repo = os.environ["GITHUB_REPOSITORY"]
    marker = f"<!-- gitops:{args.marker} -->"
    with open(args.body_file) as f:
        body = f"{marker}\n{f.read()}"[:65000]

    comments = gh_api("--paginate", "--slurp", f"repos/{repo}/issues/{args.pr}/comments")
    existing = [c for page in comments for c in page if marker in (c.get("body") or "")]
    if existing:
        gh_api("-X", "PATCH", f"repos/{repo}/issues/comments/{existing[-1]['id']}", "--input", "-", body={"body": body})
        print(f"updated comment {existing[-1]['id']}")
    else:
        created = gh_api("-X", "POST", f"repos/{repo}/issues/{args.pr}/comments", "--input", "-", body={"body": body})
        print(f"created comment {created['id']}")


if __name__ == "__main__":
    main()
