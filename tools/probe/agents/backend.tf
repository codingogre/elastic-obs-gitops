# Bucket and region come from TF_CLI_ARGS_init (scripts/with_env.py --backend).
terraform {
  backend "s3" {
    key          = "tools/probe-agents/terraform.tfstate"
    encrypt      = true
    use_lockfile = true
  }
}
