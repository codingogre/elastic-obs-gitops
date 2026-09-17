# Capabilities on Elastic Cloud Serverless

What works, and through which lane. A *lane* is the Terraform mechanism that manages an asset type. Every row was
verified live on 9.6 Serverless Observability projects on 2026-09-17 with `elastic/elasticstack` 0.16.5 and
Terraform 1.15.6 (probe roots in `tools/probe/`).

## Lanes

| Asset | Lane | Create | Update | Import | Drift clean | generate-config ok | Notes |
|---|---|---|---|---|---|---|---|
| Serverless project | `ec_observability_project` (ec 0.13.1) | n/a | n/a | ✅ | ✅ | n/a | Existing project adopted with an import block; plan shows 0 changes |
| Ingest pipeline | native `elasticstack_elasticsearch_ingest_pipeline` | ✅ | ✅ (replace on rename) | not tested | ✅ | not tested | `set event.ingested` + `lowercase` ran on a real document |
| Component template | native `elasticstack_elasticsearch_component_template` | ✅ | ✅ (replace on rename) | not tested | ✅ | not tested | Mappings only; no shard/replica settings |
| Index template (data stream, lifecycle, default pipeline) | native `elasticstack_elasticsearch_index_template` | ✅ | ✅ (replace on rename) | not tested | ✅ | not tested | `template.lifecycle.data_retention = "7d"` became the data stream's retention; `settings = {index = {default_pipeline}}` gave no diff |
| Data stream (explicit) | native `elasticstack_elasticsearch_data_stream` | ✅ | n/a (replace) | not tested | ✅ | not tested | Optional: indexing into a matching name auto-creates the stream anyway |
| Data stream lifecycle (separate) | native `elasticstack_elasticsearch_data_stream_lifecycle` | ✅ | ✅ in place | not tested | ✅ | not tested | Destroy warns "lifecycle removal skipped on serverless" (the retention stays until the stream is deleted) |
| Data view | native `elasticstack_kibana_data_view` | ✅ | ✅ (replace on id change) | not tested | ✅ | not tested | Caller-chosen `data_view.id` |
| Dashboard (typed) | native `elasticstack_kibana_dashboard` | ✅ | ✅ in place | ✅ (plus one cosmetic in-place update, then clean) | ✅ | ✅ after manual cleanup | Caller-chosen `dashboard_id`. **`access_control` does not work with an API key on 9.6 Serverless** (see below). Markdown, ES\|QL metric and ES\|QL XY panels are all representable |
| SLO (custom KQL) | native `elasticstack_kibana_slo` | ✅ | ✅ in place (revision 1 → 2, same ID) | ✅ clean once `group_by = ["*"]` is declared | ✅ | not tested | Caller-chosen `slo_id`. Computes on managed-OTLP traces |
| SLO (APM availability and latency) | native `elasticstack_kibana_slo` | ✅ | ✅ | ✅ | ✅ | not tested | **Works on managed-OTLP data** with `index = "metrics-*.otel-*"`; same good/total as the KQL SLO |
| Classic rule, ES\|QL (`.es-query`) | native `elasticstack_kibana_alerting_rule` | ✅ | ✅ in place | ✅ clean once server-default params are declared | ✅ | not tested | Caller-chosen `rule_id`. Needs the server tag `Missing Elastic Cloud API Key` in `tags` (see below). Workflows system action runs a workflow end to end |
| Classic rule, SLO burn rate | native `elasticstack_kibana_alerting_rule` | ✅ | not tested | ✅ clean | ✅ | not tested | Same tag issue |
| Workflow (as a rule target) | native `elasticstack_kibana_agentbuilder_workflow` | ✅ | not tested | not tested | ✅ | not tested | Caller-chosen `workflow_id` (a slug is accepted). Workflow IDs collide with other agents' probe objects in the same space: pick distinct prefixes |
| Maintenance window | native `elasticstack_kibana_maintenance_window` | ✅ (created disabled) | ✅ in place | not tested | ✅ | not tested | **No caller-chosen ID** (server UUID): expose as a Terraform output if anything references it |
| Kibana role | native `elasticstack_kibana_security_role` | ✅ | ✅ (replace on rename) | not tested | ✅ | not tested | Serverless accepts custom roles through the Kibana role API |
| Space | native `elasticstack_kibana_space` | ✅ (by `platform/`) | not tested here | not tested here | not tested here | n/a | `gitops-dev` exists; not re-probed |
| Stream (classic) | native `elasticstack_kibana_stream` | n/a (classic streams are import-only) | ❌ HTTP 400 | ✅ (import step itself) | n/a | not tested | **Provider 0.16.5 sends a `queries` key that 9.6 Serverless rejects.** Wired and query streams not applied in dev (they change the shared `logs.otel` root). Needs `elasticgitops` or a newer provider; verify in prod through CI |
| Synthetics monitor | native `elasticstack_kibana_synthetics_monitor` | not applied | | | | | Schema only: `browser.screenshots` accepts `"on"`, `"off"`, `"only-on-failure"` (provider validator) |
| Connector: Microsoft Teams (`.teams`) | native `elasticstack_kibana_action_connector` | ✅ | not tested | not tested (same resource as `.servicenow` ✅) | ✅ | not tested | `connector_id` UUID v4; `secrets_wo {webhookUrl}` + `secrets_wo_version`; no secret in state (grep verified); API `config:{}`; state `{"__tf_provider_context":".teams"}`, no diff. Workflow-capable. |
| Connector: ServiceNow ITSM (`.servicenow`, Table API) | native | ✅ | ✅ (in-place PUT on import) | ✅ `<space>/<uuid>`; one in-place update re-sends `secrets_wo` (version cannot be read back) | ✅ | ⚠️ emits `__tf_provider_context`, `isOAuth`, `secrets = null`; hand-clean and never apply raw | Q10: `{apiUrl, usesTableApi:true}` passes through; Kibana adds `isOAuth:false` + null OAuth keys; provider normalizes; no perpetual diff. `is_deprecated:true` is expected. Workflow-capable. |
| Connector: PagerDuty (`.pagerduty`) | native | ✅ | not tested | not tested | ✅ | not tested | `secrets_wo {routingKey}` (32 characters); API `config:{"apiUrl":null}`, state `{"__tf_provider_context":".pagerduty"}`, no diff. Workflow-capable (`agentBuilder` not listed). |
| Connector: GitHub dispatch (`.webhook`) | native | ✅ | not tested | not tested | ✅ | not tested | Token as `secrets_wo {secretHeaders {Authorization}}` (accepted; key confirmed by the internal `secret_headers` route); `hasAuth:false` works (Kibana sets `authType:null`). **`.webhook` is not workflow-capable** (`supported_feature_ids` alerting/uptime/siem). Use it only for classic rule actions. |
| Connector: GitHub dispatch (`.http`) | native | ✅ with caveat | not tested | not tested | ✅ | not tested | Workflow and Agent Builder capable. The provider has no `.http` handler: `config` must state `hasAuth = true`, `authType = "webhook-authentication-basic"`, `hasProxyAuth = false`, or apply fails ("inconsistent result") or returns 400 (`hasAuth:false` → "authType must be null or undefined"). Token as `secretHeaders.Authorization`. Real dispatch (step type, auth header behavior) not yet tested. |
| Workflows | native `elasticstack_kibana_agentbuilder_workflow` | ✅ | ✅ in place (version 1→2) | ✅ `<space>/<workflow_id>` pure import | ✅ | ✅ lossless content (escaped one-line string; decode to `.yaml`) | Caller-chosen `workflow_id` slug accepted; YAML stored byte-identical (comments kept); space-aware. **Destroy is a soft delete → re-create with the same ID returns 409 `Workflow with id '…' already exists`**; purge with `DELETE /api/workflows?force=true {"ids":[…]}` (see §4.1). |
| Agent Builder tools (esql) | native `elasticstack_kibana_agentbuilder_tool` | ✅ | ✅ in place | ✅ `<space>/<tool_id>` pure | ✅ | ✅ (query inlined; move to `.esql`) | `configuration = jsonencode({query = file(.esql), params = {name = {type, description}}})`; `_execute` returned rows; API adds `confirmation`/`schema` without diffs; space-aware; ID reusable after destroy. |
| Agent Builder tools (workflow) | native | ✅ | not tested | ✅ (generate-config plan, pure import) | ✅ | ✅ | `configuration = jsonencode({workflow_id = <workflow>.workflow_id})`; API derives the parameter schema from the workflow's manual-trigger inputs. |
| Agent Builder skills | native `elasticstack_kibana_agentbuilder_skill` | ✅ | not tested | ✅ `<space>/<skill_id>` pure | ✅ | ✅ (content inlined; move to `.md`) | Q6: `content` markdown via `file()` (byte-identical), `tool_ids` set attaches tools, optional `referenced_content [{name, relative_path "./…", content}]`; skills attach to agents with `agent.skill_ids`. |
| Agent Builder agents | native `elasticstack_kibana_agentbuilder_agent` | ✅ | ✅ in place | ✅ `<space>/<agent_id>` pure | ✅ | ✅ | `instructions`, `tools` (set of tool IDs), `skill_ids`, `labels`; **no model/connector attribute** (converse used the default `.anthropic-claude-5-sonnet-chat_completion`); **`access_control.access_mode` defaults to `private`** and is not exposed by the provider (visibility to other users not verified). Converse via `POST /s/<space>/api/agent_builder/converse` answered in 20 s and persists a conversation. |

## Caller-chosen IDs

| Resource | ID attribute | Notes |
|---|---|---|
| Dashboard | `dashboard_id` | Any slug; import `<space>/<id>` |
| SLO | `slo_id` | 8 to 48 letters, digits, `-`, `_` |
| Classic rule | `rule_id` | Any format |
| Data view | `data_view.id` | Any slug |
| Connector | `connector_id` | **UUID v1/v4 only**; fixed UUIDs are committed in code |
| Workflow | `workflow_id` | Any slug |
| Agent Builder tool, skill, agent | `tool_id`, `skill_id`, `agent_id` | Required and chosen by us |
| Maintenance window | none | Server UUID; expose as an output if referenced |

Kibana objects are space-aware: an object created under `/s/<space>` returns 404 from other spaces.

## Things that behave unexpectedly

- **Dashboard `access_control`.** Setting `write_restricted` with an API key fails on 9.6 Serverless: the provider
  reports an inconsistent result (GET omits the field) and the Dashboards API returns HTTP 500. Not used until it is
  re-verified.
- **Classic rules gain a server tag.** Rules created with a project API key get the tag
  `Missing Elastic Cloud API Key`. Declare it in `tags`, or the first apply reports an inconsistent result. Declare
  server-default params (`aggType`, `groupBy`, `excludeHitsFromPreviousRun`) for clean imports.
- **SLO imports** need `group_by = ["*"]` declared.
- **Workflow destroy is a soft delete.** Re-creating the same `workflow_id` returns HTTP 409 until the workflow is
  purged with `DELETE /api/workflows?force=true` and body `{"ids": [...]}`.
- **`.webhook` connectors cannot be called from workflows** (alerting, uptime and SIEM only). Workflows reach GitHub
  through a `.http` connector, which the provider accepts only with `hasAuth = true`,
  `authType = "webhook-authentication-basic"` and `hasProxyAuth = false` stated in `config`.
- **Agents are private by default** (`access_control.access_mode = "private"`); the provider does not expose it.
- **Agents have no model attribute**; conversations use the project's default LLM connector.
- **`elasticstack_kibana_stream` 0.16.5 cannot update** 9.6 Serverless streams (HTTP 400 `unrecognized_keys: queries`).
- **Data stream lifecycle removal** is skipped on Serverless when the lifecycle resource is destroyed; deleting the
  stream removes it.
- **generate-config output needs cleanup** before commit: dashboards (drop panel `config_json` and nulls, add required
  `query`, `refresh_interval`, fitting and axis titles), workflows (decode the escaped YAML string back into a file),
  skills and tools (move content to `.md` and `.esql` files), connectors (never apply raw: secrets come back null).

## Workflows (verified with `POST /api/workflows/test`)

- Step outputs are read from `GET /api/workflows/executions/{id}?includeOutput=true` under `stepExecutions[]`
  (take the last entry per step: retries and timeouts add entries); workflow outputs are at `context.output`.
- `waitForApproval` pauses a run in `waiting_for_input`. Approve with
  `POST /api/workflows/executions/{id}/resume` and `{"input": {"approved": true}}`; cancel with `.../cancel`. A timed-out
  approval completes with `approved: false` rather than failing, so check `approved` explicitly. Public resume links
  exist only for Slack; a card links to the run in Kibana (`{{ execution.url }}`).
- `kibana.request` does not add the workflow's space: use `path: /s/{{ workflow.spaceId }}/api/...`.
- Liquid: `url_encode` exists, `url` does not. `{{ now }}` renders as a JavaScript date string; format it with `date`.
- Build a Teams Adaptive Card as an object in a `data.set` step and send `message: "{{ variables.card | json }}"`;
  hand-escaped double-encoded JSON breaks on a double quote in any value.
- `settings.concurrency` with key `<episode_id>-<episode_status>`, `strategy: drop`, `max: 1`, plus a trailing 20 s
  `wait`, turns duplicate Alerting v2 dispatches into `skipped` runs.
- Classic rules start a workflow through the system action `system-connector-.workflows` with
  `{subAction: run, subActionParams: {workflowId, summaryMode, alertStates}}`.
- `POST /api/workflows/validate` returns 400 on Serverless.

## Telemetry (managed OTLP)

- Endpoint: the Kibana URL with `.kb.` replaced by `.ingest.`; header `Authorization: ApiKey <key>`.
- Traces land in `traces-generic.otel-default`, logs in `logs-generic.otel-default`; 1-minute rollups in
  `metrics-*.1m.otel-default` (without `service.version`, so version comparisons read raw traces).
- ES|QL accepts top-level aliases: `service.name`, `service.version`, `deployment.environment`, `http.route`,
  `http.response.status_code`. Span kind is `kind` (`Server`/`Client`); `status.code` is `"Error"` only on errors;
  `duration` is nanoseconds; `transaction.duration.us` is microseconds. Logs: `log.level`, `message`.
- APM-indicator SLOs work on managed-OTLP data with `index = "metrics-*.otel-*"`.

## Found while building the bundle (2026-09-17)

**Connectors**
- The GitHub dispatch `.http` connector works with `hasAuth = true`, `authType = "webhook-authentication-basic"`,
  `hasProxyAuth = false` and no basic credentials: only the secret header `Authorization: Bearer <token>` is sent.
  `repository_dispatch` returns 204. `_execute` params are `{method, path, body}`; an upstream non-2xx still returns
  HTTP 200 from Kibana with `status: error`.
- ServiceNow `pushToService` returns `{id, title (INC number), url, pushedDate}`. `closeIncident` with
  `{incident: {correlation_id, externalId: null}}` closes it; Kibana supplies `close_code` and close notes.
- PagerDuty `_execute` returns `{status: success, message, dedup_key}`.
- **A saved plan file (`plan -out`) contains every input variable in clear text, sensitive ones included.** Plan
  files are created and applied inside one job and never uploaded.

**Dashboards (typed resource)**
- ES|QL data-table columns must declare Kibana's defaults (rows: `alignment left, click_filter false, color auto,
  visible true`; metrics: `alignment right, color auto, visible true`) or create fails with an inconsistent result.
- ES|QL XY charts accept only data layers, so a threshold line is a constant column.
- Dashboard `tags` are tag saved-object IDs; Serverless has no tagging API.
- Import shows one cosmetic in-place update (computed `config_json`, JSON whitespace, `legend.size`), then plans clean.

**SLOs and rules**
- The APM latency indicator (`sli.apm.transactionDuration`) also works on managed-OTLP data.
- Burn-rate `maxBurnRateThreshold` is the SLO window in hours divided by the long window in hours (168, 28 and 7
  for a 7-day SLO with 1h, 6h and 24h long windows).

**Workflows**
- `{{ kibanaUrl }}` is the Kibana base URL without the space.
- ES|QL steps take positional `params` only and accept a `filter` range on `@timestamp`.
- The workflow `http` step with `connector-id` of a `.http` connector returns `{status, statusText, headers, data}`.
- The first ES|QL query against `traces-*` can be cold (38 s once); steps carry a timeout and a retry.

**Agent Builder**
- A skill can reference at most five tools (HTTP 400).
- ES|QL tool parameter types: string, integer, float, boolean, date, array; create checks syntax and parameter use,
  not index existence.
- Agents created through the API are `access_mode: private` and owned by the API key's user;
  `PUT /api/agent_builder/agents/{id}` with `{"access_control": {"access_mode": "shared"}}` changes it (not in the
  provider).
- `get_index_mapping` on a busy `traces-*` returns about 200k tokens; the reviewer does not use it.
- Converse times: reviewer about 75 s, remediator about 56 s, assistant about 20 s.
