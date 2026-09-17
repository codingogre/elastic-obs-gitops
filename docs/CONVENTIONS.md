# Conventions

Every managed object has an explicit, stable ID that is identical in every environment. Nothing that is promoted
depends on a server-generated ID. Environment differences live only in `envs/<env>/terraform.tfvars` and credentials.

## Where things live

| Kind | Module | Notes |
|---|---|---|
| Event stream, gate index, data views, connectors, Control Tower, operator role | `modules/bundle/foundation` | Platform-owned; Control Tower ES\|QL in `queries/control-tower/*.esql` |
| Per-service dashboard, SLOs, rules, gate, agent tool | `modules/bundle/service-observability` | One instance per `catalog/services/*.yaml` |
| Workflows | `modules/bundle/workflows` | YAML in `*.yaml` files |
| Agents, skills, tools | `modules/bundle/agents` | Skills in `skills/*.md`, ES\|QL in `tools/*.esql` |
| Alerting v2 routing | `modules/bundle/alerting_v2` | `elasticgitops` resources, behind `settings.alerting_v2_enabled` |
| Captured UI objects | `modules/bundle/bespoke` | Written by the capture flow (`dashboards/<slug>.json`, `workflows/<id>.yaml`) |

## IDs

`<svc>` is the catalog `name`, for example `grid-dispatch`.

| Object | ID | Display name |
|---|---|---|
| Data stream | `gitops-events` | |
| Gate definitions index | `gitops-gates` (document ID `gate-<svc>`) | |
| Data views | `gitops-dv-traces`, `gitops-dv-logs`, `gitops-dv-gitops-events` | Traces, Logs, GitOps events |
| Connector: Teams | `abd684be-bb1c-4dec-81ba-ce4e6922bad3` | `gitops-teams` |
| Connector: ServiceNow ITSM | `846af0d6-5963-4c2d-b510-f48d525999f8` | `gitops-servicenow` |
| Connector: PagerDuty | `49d5a547-b980-426b-a5a4-f00f3ab6e473` | `gitops-pagerduty` |
| Connector: GitHub dispatch (`.http`) | `e5ab5e5b-6f2b-488a-b140-a474987298bf` | `gitops-github-dispatch` |
| Workflow: release gate | `gitops-release-gate` | Release gate |
| Workflow: remediation | `gitops-remediate-service` | Remediate service |
| Workflow: sync UI change to Git | `gitops-sync-to-git` | Sync to Git |
| Workflow: post a card | `gitops-post-card` | Post card |
| Agent: plan reviewer | `gitops-reviewer` | GitOps reviewer |
| Agent: developer helper | `gitops-platform-assistant` | Platform assistant |
| Agent: SRE triage | `gitops-sre-remediator` | SRE remediator |
| Skill: review checklist | `gitops-observability-review` | |
| Skill: release risk | `gitops-release-risk-assessment` | |
| Tools (shared) | `gitops-rule-backtest`, `gitops-slo-feasibility`, `gitops-recent-deploys`, `gitops-error-ratio-by-version` | Field checks use the built-in read-only tools |
| Tool (workflow) | `gitops-sync-to-git-tool` | Only where `settings.drift_policy = "capture"` (dev) |
| Tool (per service) | `gitops-svc-<svc>-health` | |
| Dashboard (per service) | `svc-<svc>-golden-signals` | `<Title> golden signals` |
| SLOs (per service) | `svc-<svc>-availability`, `svc-<svc>-latency` | |
| Classic rules (per service) | `svc-<svc>-availability-burn-rate`, `svc-<svc>-latency-burn-rate` | |
| Alerting v2 rule (per service) | `svc-<svc>-error-spike` | |
| Alerting v2 action policy | `gitops-route-remediation` (matches tag `gitops-remediation`) | |
| Control Tower dashboard | `ops-gitops-control-tower` | GitOps Control Tower |
| Kibana role for people (only where `settings.operator_role`) | `gitops-operator` | Assigned by hand as an Elastic Cloud project role |

## Tags and labels

- Every Kibana object that supports tags carries `gitops` and, where it belongs to a service, `service:<svc>`.
  Dashboards are the exception: their tags are tag saved-object IDs, and Serverless has no tagging API.
- Classic rules also declare `Missing Elastic Cloud API Key`, which Serverless adds to rules created with a project
  API key (see `CAPABILITIES.md`).

## Events

`gitops-events` documents use `event.action` from: `plan`, `apply`, `tag`, `promotion`, `capture`, `drift_detected`,
`drift_reverted`, `gate_evaluated`, `release_started`, `release_succeeded`, `rollback`, `remediation`, `onboarded`.

## GitHub dispatch event types

| `event_type` | Sent by | Handled by |
|---|---|---|
| `capture-ui-change` | `gitops-sync-to-git` | `capture-dev.yml` |
| `rollback` | `gitops-remediate-service` after approval | `rollback-app.yml` |

## Records in response tools

Anything created in ServiceNow, PagerDuty or Teams is created by an Elastic connector and its title starts with
`[GITOPS-DEMO]`.

## Settings

`settings` is declared in every module that takes it and in both `envs/*/variables.tf`. Prod's root files come from
`main`, but prod's bundle is pinned to a tag. **Adding** a field is safe (an older pinned bundle ignores it).
**Renaming or removing** a field breaks every prod plan until prod pins a tag that has the change: promote such a
change before anything else plans prod, and never pin prod to an older tag past it.
