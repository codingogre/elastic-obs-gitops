#!/usr/bin/env python3
"""Run a command with one environment's credentials loaded, without a shell ever parsing them.

Usage: with_env.py <dev|prod|platform> [--backend] -- <command> [args...]

Locally, KEY=VALUE files are read from the directory named by GITOPS_ENV_DIR (default: the repo's
parent directory): .env.<env>, .env.tools (response-tool credentials) and .env.state. In CI the variables already come from GitHub
Environment secrets, so missing files are fine. Values are never printed.

Well-known names are mapped to Terraform input variables (TF_VAR_*) unless already set. With
--backend, TF_CLI_ARGS_init carries the S3 bucket and region for `terraform init`.
"""
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ENV_DIR = Path(os.environ.get("GITOPS_ENV_DIR", REPO.parent))

# environment variable -> Terraform variable
TF_VARS = {
    "ELASTICSEARCH_ENDPOINTS": "elasticsearch_endpoint",
    "ELASTICSEARCH_API_KEY": "elasticsearch_api_key",
    "KIBANA_ENDPOINT": "kibana_endpoint",
    "KIBANA_API_KEY": "kibana_api_key",
    "TEAMS_WEBHOOK_URL": "teams_webhook_url",
    "SN_URL": "sn_url",
    "SN_USER": "sn_user",
    "SN_PASSWORD": "sn_password",
    "PD_ROUTING_KEY": "pd_routing_key",
    "GH_DISPATCH_TOKEN": "github_dispatch_token",
}


def read_env_file(path):
    values = {}
    if not path.is_file():
        return values
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def main():
    args = sys.argv[1:]
    if "--" not in args or not args or args[0] not in ("dev", "prod", "platform"):
        sys.exit(__doc__)
    split = args.index("--")
    env_name, flags, command = args[0], args[1:split], args[split + 1:]

    env = dict(os.environ)
    state = read_env_file(ENV_DIR / ".env.state")
    for key, value in state.items():
        env.setdefault(key, value)

    if env_name == "platform":
        # Cloud organization key (ec provider) plus the dev project's Kibana (gitops-dev space).
        prod = read_env_file(ENV_DIR / ".env.prod")
        dev = read_env_file(ENV_DIR / ".env.dev")
        if prod.get("EC_CLOUD_API_KEY"):
            env.setdefault("EC_API_KEY", prod["EC_CLOUD_API_KEY"])
        if prod.get("PROJECT_ID"):
            env.setdefault("TF_VAR_prod_project_id", prod["PROJECT_ID"])
        for key, var in (("KIBANA_ENDPOINT", "dev_kibana_endpoint"), ("KIBANA_API_KEY", "dev_kibana_api_key")):
            if dev.get(key):
                env.setdefault(f"TF_VAR_{var}", dev[key])
    else:
        # Response-tool credentials (.env.tools) are shared by both environments.
        for name in (f".env.{env_name}", ".env.tools"):
            for key, value in read_env_file(ENV_DIR / name).items():
                env.setdefault(key, value)
        for key, var in TF_VARS.items():
            if env.get(key):
                env.setdefault(f"TF_VAR_{var}", env[key])

    # A locally built elasticgitops provider (make provider) is used when present; CI builds its own mirror.
    local_rc = REPO / ".provider-mirror" / "terraformrc"
    if local_rc.is_file():
        env.setdefault("TF_CLI_CONFIG_FILE", str(local_rc))

    if "--backend" in flags:
        bucket, region = env.get("TF_STATE_BUCKET"), env.get("TF_STATE_REGION")
        if not bucket or not region:
            sys.exit("TF_STATE_BUCKET and TF_STATE_REGION must be set for --backend")
        env["TF_CLI_ARGS_init"] = f"-backend-config=bucket={bucket} -backend-config=region={region}"

    os.execvpe(command[0], command, env)


if __name__ == "__main__":
    main()
