# Bucket and region come from TF_CLI_ARGS_init (scripts/with_env.py --backend, or CI variables).
terraform {
  backend "s3" {
    key          = "tools/probe-core/terraform.tfstate"
    encrypt      = true
    use_lockfile = true
  }
}
