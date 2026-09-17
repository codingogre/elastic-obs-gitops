#!/usr/bin/env python3
"""One-off Phase 0 cleanup: delete the exception-event log documents whose stack traces contain a local
workstation path. They were written by the first version of scripts/traffic.py between 12:50 and 13:10 UTC
on 2026-09-17 and are limited to the two demo services. Data only; no configuration is touched.

Usage: python3 scripts/with_env.py <dev|prod> -- python3 tools/probe/api/purge_path_docs.py
"""
import json
import os
import ssl
import urllib.error
import urllib.request

CTX = ssl.create_default_context(cafile="/etc/ssl/cert.pem")
BASE = os.environ["ELASTICSEARCH_ENDPOINTS"].split(",")[0].rstrip("/")
HEADERS = {"Authorization": "ApiKey " + os.environ["ELASTICSEARCH_API_KEY"], "Content-Type": "application/json"}
QUERY = {"query": {"bool": {"filter": [
    {"terms": {"service.name": ["grid-dispatch", "turbine-telemetry"]}},
    {"wildcard": {"exception.stacktrace": "*/Users/*"}},
    {"range": {"@timestamp": {"gte": "2026-09-17T12:50:00Z", "lte": "2026-09-17T13:10:00Z"}}},
]}}}


def call(path):
    req = urllib.request.Request(BASE + path, data=json.dumps(QUERY).encode(), method="POST", headers=HEADERS)
    try:
        return json.load(urllib.request.urlopen(req, context=CTX, timeout=120))
    except urllib.error.HTTPError as e:
        return {"error": e.code, "body": e.read().decode()[:300]}


print("matching before:", call("/logs-generic.otel-default/_count").get("count"))
result = call("/logs-generic.otel-default/_delete_by_query?conflicts=proceed&refresh=true")
print("deleted:", result.get("deleted"), "failures:", result.get("failures"), result.get("error", ""))
print("matching after:", call("/logs-generic.otel-default/_count").get("count"))
