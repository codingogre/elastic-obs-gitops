#!/usr/bin/env python3
"""Copy local credentials into GitHub Actions secrets without printing them.

Usage: sync_github_secrets.py [--dry-run]

Reads .env.dev, .env.prod, .env.tools and .env.state from GITOPS_ENV_DIR (default: the repo's parent
directory) and sets environment secrets (dev, prod, platform) and repository secrets. Each scope is one
`gh secret set --env-file -` call; the values travel on stdin only. Empty values are skipped and listed.
Safe to re-run: setting a secret overwrites it.
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
TIMEOUT_S = 90

REPO_DIR = Path(__file__).resolve().parent.parent


def repository():
    """owner/name from this checkout's git remote, so the script works from any directory."""
    result = subprocess.run(["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"],
                            cwd=REPO_DIR, text=True, capture_output=True, timeout=TIMEOUT_S)
    if result.returncode != 0:
        sys.exit(f"sync: cannot resolve the GitHub repository: {result.stderr.strip()}")
    return result.stdout.strip()


def put_scope(repo, env, secrets, dry_run):
    """Set every non-empty secret of one scope (an environment, or the repository when env is None)."""
    target = f"env {env}" if env else "repo"
    lines, names = [], []
    for name, value in secrets:
        if not value:
            print(f"skip  {target:>12}  {name} (empty)")
            continue
        if "'" in value or "\n" in value:
            sys.exit(f"sync: {name} contains a quote or newline; set it by hand with gh secret set")
        # Single quotes keep the value literal in dotenv parsing (no $VAR expansion).
        lines.append(f"{name}='{value}'")
        names.append(name)
    if not names:
        return
    if not dry_run:
        cmd = ["gh", "secret", "set", "--repo", repo, "--env-file", "-"] + (["--env", env] if env else [])
        try:
            result = subprocess.run(cmd, input="\n".join(lines) + "\n", text=True, capture_output=True,
                                    cwd=REPO_DIR, timeout=TIMEOUT_S)
        except subprocess.TimeoutExpired:
            sys.exit(f"sync: gh did not finish setting {target} secrets within {TIMEOUT_S}s")
        if result.returncode != 0:
            # gh's stderr names secrets but never contains their values.
            sys.exit(f"sync: gh secret set ({target}) failed: {result.stderr.strip()}")
    for name in names:
        print(f"set   {target:>12}  {name}")


def main():
    dry_run = "--dry-run" in sys.argv
    repo = repository()
    print(f"repository: {repo}")
    tools = read_env_file(ENV_DIR / ".env.tools")
    state = read_env_file(ENV_DIR / ".env.state")
    dev = read_env_file(ENV_DIR / ".env.dev")
    prod = read_env_file(ENV_DIR / ".env.prod")

    # prod-automation holds the prod credentials for jobs that need no approver: application releases and the
    # drift revert, which only re-applies what Git already says.
    for env_name, values in (("dev", dev), ("prod", prod), ("prod-automation", prod)):
        merged = {**tools, **values}
        put_scope(repo, env_name, [(n, merged.get(n, "")) for n in ELASTIC + TOOLS], dry_run)

    put_scope(repo, "platform", [
        ("EC_API_KEY", prod.get("EC_CLOUD_API_KEY", "")),
        ("PROD_PROJECT_ID", prod.get("PROJECT_ID", "")),
        ("DEV_KIBANA_ENDPOINT", dev.get("KIBANA_ENDPOINT", "")),
        ("DEV_KIBANA_API_KEY", dev.get("KIBANA_API_KEY", "")),
    ], dry_run)

    merged = {**state, **tools}
    put_scope(repo, None, [(n, merged.get(n, "")) for n in REPO_SECRETS], dry_run)


if __name__ == "__main__":
    main()
