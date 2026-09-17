# Bucket and region come from TF_CLI_ARGS_init (scripts/with_env.py --backend, or CI).
terraform {
  backend "s3" {
    key          = "envs/prod/terraform.tfstate"
    encrypt      = true
    use_lockfile = true
  }
}
