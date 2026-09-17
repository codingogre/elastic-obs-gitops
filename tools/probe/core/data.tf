# Lane: Elasticsearch data (component template, index template with data stream lifecycle, ingest pipeline,
# explicit data stream, separate data stream lifecycle). Serverless rejects shard and replica settings, so none are set.

locals {
  events = "${var.prefix}-events"
}

resource "elasticstack_elasticsearch_ingest_pipeline" "events" {
  name        = local.events
  description = "Probe: stamp event.ingested and lowercase event.action."

  processors = [
    jsonencode({
      set = {
        field = "event.ingested"
        value = "{{{_ingest.timestamp}}}"
      }
    }),
    jsonencode({
      lowercase = {
        field          = "event.action"
        ignore_missing = true
      }
    }),
  ]
}

resource "elasticstack_elasticsearch_component_template" "events_mappings" {
  name = "${local.events}-mappings"

  template {
    mappings = jsonencode({
      properties = {
        "@timestamp" = { type = "date" }
        message      = { type = "text" }
        event = {
          properties = {
            action   = { type = "keyword" }
            kind     = { type = "keyword" }
            ingested = { type = "date" }
          }
        }
        service = {
          properties = {
            name = { type = "keyword" }
          }
        }
      }
    })
  }
}

resource "elasticstack_elasticsearch_index_template" "events" {
  name           = local.events
  index_patterns = ["${local.events}*"]
  composed_of    = [elasticstack_elasticsearch_component_template.events_mappings.name]
  priority       = 500

  data_stream {}

  template {
    settings = jsonencode({
      index = {
        default_pipeline = elasticstack_elasticsearch_ingest_pipeline.events.name
      }
    })

    lifecycle {
      data_retention = "7d"
    }
  }
}

# A second data stream, created explicitly, carries the separate lifecycle lane so the template-level
# lifecycle on the first one stays observable on its own.
resource "elasticstack_elasticsearch_data_stream" "events_explicit" {
  name = "${local.events}-explicit"

  depends_on = [elasticstack_elasticsearch_index_template.events]
}

resource "elasticstack_elasticsearch_data_stream_lifecycle" "events_explicit" {
  name           = elasticstack_elasticsearch_data_stream.events_explicit.name
  data_retention = "3d"
}
