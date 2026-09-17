# elastic-obs-gitops

Observability as code for Elastic Cloud Serverless: dashboards, SLOs, alerting, response routing, workflows and AI agents live in Git and reach production through reviewed, gated pull requests.

**Only Terraform writes configuration. Anything may read.**

## How it fits together

| Layer | Path | What it does |
|---|---|---|
| Platform | `platform/` | Adopts the prod Serverless Observability project (`ec`) and creates the dev Kibana space |
| Bundle | `modules/bundle/` | The single versioned unit of promotion: foundation assets, the golden-path module per catalog service, alerting, workflows and agents |
| Environments | `envs/dev`, `envs/prod` | Root modules. Dev tracks `main`; prod pins a tagged bundle release (`obs-vX.Y.Z`) |
| Pipelines | `.github/workflows/` | Plan and review on pull requests, apply dev on merge, gated promotion to prod, drift revert, UI capture, releases |

Environment differences live only in `envs/<env>/terraform.tfvars` and in credentials. Every managed object has an explicit, stable ID, so the same bundle produces identical objects in every environment.

Terraform resources that the `elastic/elasticstack` provider does not cover yet (Alerting v2 rules and action policies, raw dashboard JSON, Kibana settings, release gates) come from [`codingogre/terraform-provider-elasticgitops`](https://github.com/codingogre/terraform-provider-elasticgitops).

## Working locally

Credentials are never stored in this repository. Locally, `scripts/with_env.py` reads `.env.dev`, `.env.prod` and `.env.state` from the directory above the checkout (or `GITOPS_ENV_DIR`) and passes them to Terraform without a shell parsing them. In CI they come from GitHub Environment secrets.

```sh
make init ENV=dev
make plan ENV=dev
make apply ENV=dev      # prod is applied only by the apply-prod job
```

State lives in an encrypted, versioned S3 bucket with native locking; CI reaches it through a GitHub OIDC role.

## Docs

- `docs/CAPABILITIES.md`: what works on Serverless, and through which lane
- `docs/DECISIONS.md`: short decision records
