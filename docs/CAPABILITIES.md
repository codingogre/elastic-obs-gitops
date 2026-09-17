# Capabilities on Elastic Cloud Serverless

What works, and through which lane. A *lane* is the Terraform mechanism that manages an asset type. Every row was
verified live against a 9.6 Serverless Observability project; the date is in the notes.

| Asset | Lane | Create | Update | Import | Drift clean | generate-config ok | Notes |
|---|---|---|---|---|---|---|---|
| Serverless project | `ec_observability_project` | n/a | n/a | ✅ | ✅ | n/a | Existing project adopted with an import block; plan shows 0 changes (2026-09-17) |
| Kibana space | `elasticstack_kibana_space` | ✅ | | | ✅ | | Second plan clean (2026-09-17) |
