# Decisions

Short decision records, newest last.

## ADR-001: Terraform state in S3 with GitHub OIDC (2026-09-17)

**Decision.** Every root module uses the `s3` backend with `encrypt = true` and `use_lockfile = true` (native S3
locking, no DynamoDB table). The bucket is private, versioned and encrypted. GitHub Actions assumes an IAM role
through OIDC; the role trusts only this repository and can only read and write objects in the state bucket.

**Why.** No long-lived cloud keys in GitHub, and nothing to sign up for. The bucket name and role ARN are not in the
repository: locally they come from `.env.state`, in CI from repository variables.

## ADR-002: the elasticgitops provider is built from source; lock files are not committed (2026-09-17)

**Decision.** CI builds `codingogre/elasticgitops` from source into a filesystem mirror and points Terraform at it
with `provider_installation`. The source address is the Registry address, so publishing later changes nothing in
the modules. `.terraform.lock.hcl` is gitignored and every provider version is pinned exactly in `versions.tf`.

**Why.** A provider built per platform has platform-specific checksums, so a committed lock file would not verify on
both a laptop and a CI runner.

## ADR-003: credentials reach Terraform through `scripts/with_env.py` (2026-09-17)

**Decision.** Local commands run through `scripts/with_env.py <env> -- <command>`, which reads `KEY=VALUE` files
without a shell and maps well-known names to `TF_VAR_*`. CI sets the same variables from Environment secrets.

**Why.** Credential values can contain shell metacharacters, and they must never be printed or sourced.

## ADR-004: platform applies to prod run in CI; dev-only targets may run locally (2026-09-17)

**Decision.** `platform/` holds the prod project (imported) and the dev space. Locally, only
`-target=elasticstack_kibana_space.gitops_dev` is applied. Adopting the prod project runs in the `platform`
job in the `prod` environment.

**Why.** Prod changes land only through a reviewed CI job, even when the plan shows none.
