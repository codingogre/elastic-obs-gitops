#!/usr/bin/env python3
"""Copy local credentials into GitHub Actions secrets without printing them.

Usage: sync_github_secrets.py [--dry-run]

Reads .env.dev, .env.prod, .env.tools and .env.state from GITOPS_ENV_DIR (default: the repo's parent
directory) and sets environment secrets (dev, prod, platform) and repository secrets with `gh secret set`,
passing each value on stdin. Empty values are skipped and listed.
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from with_env import ENV_DIR, read_env_file  # noqa: E402

ELASTIC = ["ELASTICSEARCH_ENDPOINTS", "ELASTICSEARCH_API_KEY", "KIBANA_ENDPOINT", "KIBANA_API_KEY",
           "KIBANA_SPACE", "OTLP_ENDPOINT"]
TOOLS = ["TEAMS_WEBHOOK_URL", "SN_URL", "SN_USER", "SN_PASSWORD", "PD_ROUTING_KEY"]
REPO_SECRETS = ["TF_STATE_BUCKET", "TF_STATE_REGION", "AWS_ROLE_ARN", "GH_DISPATCH_TOKEN"]


REPO_DIR = Path(__file__).resolve().parent.parent


def repository():
    """owner/name from this checkout's git remote, so the script works from any directory."""
    result = subprocess.run(["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"],
                            cwd=REPO_DIR, text=True, capture_output=True)
    if result.returncode != 0:
        sys.exit(f"sync: cannot resolve the GitHub repository: {result.stderr.strip()}")
    return result.stdout.strip()


def put(repo, name, value, env=None, dry_run=False):
    target = f"env {env}" if env else "repo"
    if not value:
        print(f"skip  {target:>12}  {name} (empty)")
        return
    if not dry_run:
        cmd = ["gh", "secret", "set", name, "--repo", repo] + (["--env", env] if env else [])
        # The value goes on stdin only; gh's stderr never contains it.
        result = subprocess.run(cmd, input=value, text=True, capture_output=True, cwd=REPO_DIR)
        if result.returncode != 0:
            sys.exit(f"sync: gh secret set {name} ({target}) failed: {result.stderr.strip()}")
    print(f"set   {target:>12}  {name}")


def main():
    dry_run = "--dry-run" in sys.argv
    repo = repository()
    print(f"repository: {repo}")
    tools = read_env_file(ENV_DIR / ".env.tools")
    state = read_env_file(ENV_DIR / ".env.state")
    dev = read_env_file(ENV_DIR / ".env.dev")
    prod = read_env_file(ENV_DIR / ".env.prod")

    for env_name, values in (("dev", dev), ("prod", prod)):
        merged = {**tools, **values}
        for name in ELASTIC + TOOLS:
            put(repo, name, merged.get(name, ""), env_name, dry_run)

    put(repo, "EC_API_KEY", prod.get("EC_CLOUD_API_KEY", ""), "platform", dry_run)
    put(repo, "PROD_PROJECT_ID", prod.get("PROJECT_ID", ""), "platform", dry_run)
    put(repo, "DEV_KIBANA_ENDPOINT", dev.get("KIBANA_ENDPOINT", ""), "platform", dry_run)
    put(repo, "DEV_KIBANA_API_KEY", dev.get("KIBANA_API_KEY", ""), "platform", dry_run)

    merged = {**state, **tools}
    for name in REPO_SECRETS:
        put(repo, name, merged.get(name, ""), None, dry_run)


if __name__ == "__main__":
    main()
