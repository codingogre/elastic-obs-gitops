# gitops-events: the pipeline's own telemetry (plans, applies, promotions, gate verdicts, drift, releases).

resource "elasticstack_elasticsearch_component_template" "gitops_events_mappings" {
  name = "gitops-events@mappings"

  template {
    mappings = jsonencode({
      dynamic = false
      properties = {
        "@timestamp" = { type = "date" }
        message      = { type = "text" }
        event = {
          properties = {
            action   = { type = "keyword" }
            outcome  = { type = "keyword" }
            ingested = { type = "date" }
          }
        }
        gitops = {
          properties = {
            env              = { type = "keyword" }
            bundle_version   = { type = "keyword" }
            service          = { type = "keyword" }
            service_version  = { type = "keyword" }
            baseline_version = { type = "keyword" }
            resource_address = { type = "keyword" }
            actor            = { type = "keyword" }
            run_id           = { type = "keyword" }
            run_url          = { type = "keyword" }
            commit           = { type = "keyword" }
            pr_number        = { type = "long" }
            verdict          = { type = "keyword" }
            reasons          = { type = "keyword" }
            started_at       = { type = "date" }
            duration_s       = { type = "double" }
            details          = { type = "flattened" }
          }
        }
      }
    })
  }
}

resource "elasticstack_elasticsearch_ingest_pipeline" "gitops_events_normalize" {
  name        = "gitops-events-normalize"
  description = "Stamps ingest time, lowercases the environment and derives the duration of timed events."

  processors = [
    jsonencode({ set = { field = "event.ingested", value = "{{{_ingest.timestamp}}}" } }),
    jsonencode({ lowercase = { field = "gitops.env", ignore_missing = true } }),
    jsonencode({
      script = {
        if     = "ctx.gitops?.started_at != null && ctx['@timestamp'] != null && ctx.gitops?.duration_s == null"
        lang   = "painless"
        source = "ctx.gitops.duration_s = ChronoUnit.MILLIS.between(ZonedDateTime.parse(ctx.gitops.started_at), ZonedDateTime.parse(ctx['@timestamp'])) / 1000.0;"
      }
    }),
  ]
}

resource "elasticstack_elasticsearch_index_template" "gitops_events" {
  name           = "gitops-events"
  index_patterns = ["gitops-events*"]
  priority       = 500
  composed_of    = [elasticstack_elasticsearch_component_template.gitops_events_mappings.name]

  data_stream {}

  template {
    settings = jsonencode({
      index = { default_pipeline = elasticstack_elasticsearch_ingest_pipeline.gitops_events_normalize.name }
    })

    lifecycle {
      data_retention = var.settings.gitops_events_retention
    }
  }
}
