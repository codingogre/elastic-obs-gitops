#!/usr/bin/env python3
"""Synthetic OpenTelemetry traffic for the demo services.

Sends traces and correlated logs over OTLP/HTTP (protobuf) straight to an Elastic Managed OTLP
Endpoint, with no collector and no APM Server in between. Each simulated request is:

  * one SERVER span: HTTP method, route, URL path and status code (500 on error), with span status
    ERROR and an `exception` event when the request fails;
  * one CLIENT child span to a dependency (PostgreSQL or Kafka);
  * one log record inside the span's context (INFO on success, ERROR with the failure message).

Latency is log-normal, scaled so that its 95th percentile is close to --p95-ms. With
--degrade-after N the service runs healthy for N seconds and then turns into a latent-bug release:
the error rate and p95 switch to the --degraded-* values, and the extra errors concentrate on the
service's primary route, which is what a bad release looks like.

Connection settings come from the environment, never from arguments:
  OTLP_ENDPOINT          base URL of the managed OTLP endpoint (falls back to OTEL_EXPORTER_OTLP_ENDPOINT)
  ELASTICSEARCH_API_KEY  sent as "Authorization: ApiKey <key>"

Locally, load them with scripts/with_env.py:
  python3 scripts/with_env.py dev -- .venv/bin/python scripts/traffic.py --env dev \
      --service grid-dispatch --version 2.4.3 --rps 5 --error-rate 0.005 --p95-ms 250

SIGINT and SIGTERM flush what is buffered and exit cleanly. A heartbeat line goes to stdout every
30 seconds; it never contains the endpoint or the key.
"""
import argparse
import math
import os
import random
import signal
import sys
import time
import uuid

from opentelemetry import trace
from opentelemetry._logs import SeverityNumber
from opentelemetry.exporter.otlp.proto.http import Compression
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import SpanKind, Status, StatusCode

HEARTBEAT_SECONDS = 30
SERVICE_NAMESPACE = "energy-platform"
Z95 = 1.6449  # standard normal quantile for p95
SIGMA = 0.5  # log-normal shape: p95 is about 2.3x the median

# Routes per service: (method, route, weight, dependency). The first route is the primary route,
# where a latent bug shows up after --degrade-after.
SERVICES = {
    "grid-dispatch": {
        "routes": [
            ("POST", "/dispatch", 0.35, "kafka"),
            ("GET", "/grid/{region}/load", 0.45, "postgresql"),
            ("GET", "/dispatch/{id}", 0.20, "postgresql"),
        ],
        "bug": ("ValueError", "dispatch setpoint exceeds unit ramp limit"),
        "topic": "dispatch-commands",
        "database": "dispatch",
    },
    "turbine-telemetry": {
        "routes": [
            ("POST", "/telemetry/batch", 0.70, "kafka"),
            ("GET", "/turbines/{id}/health", 0.30, "postgresql"),
        ],
        "bug": ("KeyError", "'blade_pitch_deg' missing from telemetry frame"),
        "topic": "turbine-telemetry-raw",
        "database": "telemetry",
    },
    "field-service": {
        "routes": [
            ("POST", "/work-orders", 0.40, "postgresql"),
            ("GET", "/work-orders/{id}", 0.60, "postgresql"),
        ],
        "bug": ("RuntimeError", "work order crew assignment returned no rows"),
        "topic": "work-order-events",
        "database": "workorders",
    },
}
GENERIC = {
    "routes": [
        ("GET", "/api/items", 0.50, "postgresql"),
        ("GET", "/api/items/{id}", 0.30, "postgresql"),
        ("POST", "/api/items", 0.20, "kafka"),
    ],
    "bug": ("RuntimeError", "unexpected null payload"),
    "topic": "item-events",
    "database": "items",
}
REGIONS = ["north", "south", "east", "west", "central"]
# Ordinary failures that happen in any version.
TRANSIENT_ERRORS = [
    ("TimeoutError", "upstream call timed out after 2000 ms"),
    ("ConnectionResetError", "connection reset by peer"),
]


class CountingExporter:
    """Wraps an exporter and counts exported and failed items for the heartbeat."""

    def __init__(self, inner):
        self.inner, self.ok, self.failed = inner, 0, 0

    def export(self, batch):
        result = self.inner.export(batch)
        if result.name == "SUCCESS":
            self.ok += len(batch)
        else:
            self.failed += len(batch)
        return result

    def shutdown(self):
        return self.inner.shutdown()

    def force_flush(self, timeout_millis=30000):
        return self.inner.force_flush(timeout_millis)


def parse_args():
    p = argparse.ArgumentParser(description="Send synthetic OTel traces and logs to an Elastic managed OTLP endpoint.")
    p.add_argument("--env", required=True, choices=["dev", "prod"], help="target environment (credentials come from the environment)")
    p.add_argument("--service", required=True, help="service.name, e.g. grid-dispatch")
    p.add_argument("--version", required=True, help="service.version, e.g. 2.4.3")
    p.add_argument("--deployment-environment", help="deployment.environment.name (default: --env)")
    p.add_argument("--rps", type=float, default=5.0, help="requests per second (default 5)")
    p.add_argument("--error-rate", type=float, default=0.005, help="fraction of failed requests (default 0.005)")
    p.add_argument("--p95-ms", type=float, default=250.0, help="target p95 latency in ms (default 250)")
    p.add_argument("--duration", type=float, default=0, help="seconds to run; 0 runs until stopped (default 0)")
    p.add_argument("--degrade-after", type=float, help="seconds after start when the latent bug appears")
    p.add_argument("--degraded-error-rate", type=float, default=0.08, help="error rate once degraded (default 0.08)")
    p.add_argument("--degraded-p95-ms", type=float, help="p95 once degraded (default 3x --p95-ms)")
    p.add_argument("--run-id", help="correlation ID recorded as resource attribute gitops.run_id")
    args = p.parse_args()
    if args.rps <= 0:
        p.error("--rps must be positive")
    for name in ("error_rate", "degraded_error_rate"):
        if not 0 <= getattr(args, name) <= 1:
            p.error(f"--{name.replace('_', '-')} must be between 0 and 1")
    args.deployment_environment = args.deployment_environment or args.env
    args.degraded_p95_ms = args.degraded_p95_ms or 3 * args.p95_ms
    return args


def build_pipeline(args):
    endpoint = (os.environ.get("OTLP_ENDPOINT") or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") or "").rstrip("/")
    api_key = os.environ.get("ELASTICSEARCH_API_KEY", "")
    if not endpoint or not api_key:
        sys.exit("OTLP_ENDPOINT and ELASTICSEARCH_API_KEY must be set (use scripts/with_env.py)")
    headers = {"Authorization": f"ApiKey {api_key}"}

    attributes = {
        "service.name": args.service,
        "service.version": args.version,
        "service.namespace": SERVICE_NAMESPACE,
        "service.instance.id": f"{args.service}-{uuid.uuid4().hex[:8]}",
        "deployment.environment.name": args.deployment_environment,
        "deployment.environment": args.deployment_environment,  # older semantic-convention name
    }
    if args.run_id:
        attributes["gitops.run_id"] = args.run_id
    resource = Resource.create(attributes)

    spans = CountingExporter(OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces", headers=headers, compression=Compression.Gzip, timeout=30))
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(BatchSpanProcessor(spans, max_queue_size=20000, schedule_delay_millis=2000, max_export_batch_size=1000))

    logs = CountingExporter(OTLPLogExporter(endpoint=f"{endpoint}/v1/logs", headers=headers, compression=Compression.Gzip, timeout=30))
    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(BatchLogRecordProcessor(logs, max_queue_size=20000, schedule_delay_millis=2000, max_export_batch_size=1000))

    tracer = tracer_provider.get_tracer("gitops-traffic")
    logger = logger_provider.get_logger(args.service)
    return tracer_provider, logger_provider, tracer, logger, spans, logs


def latency_ms(p95_ms):
    """Log-normal latency whose 95th percentile is p95_ms."""
    median = p95_ms / math.exp(Z95 * SIGMA)
    return random.lognormvariate(math.log(median), SIGMA)


def concrete_path(route):
    return (route.replace("{region}", random.choice(REGIONS))
                 .replace("{id}", str(random.randint(10000, 99999))))


# Frames for synthetic stack traces, relative to /app/<service_module>/. Exception events never carry
# paths from the machine that runs this script.
HANDLER_FRAME = ("api/handlers.py", 64, "handle_request", "response = route_handler(request)")
BUG_FRAME = ("core/service.py", 118, "process", "validated = validate(payload)")
DEPENDENCY_FRAMES = {
    "kafka": ("adapters/kafka.py", 41, "send", "producer.send(topic, value).get(timeout=2)"),
    "postgresql": ("adapters/postgres.py", 57, "fetch", "rows = connection.execute(query, params)"),
}


def stacktrace(service, error_type, message, frames):
    module = service.replace("-", "_")
    lines = ["Traceback (most recent call last):"]
    for file, lineno, func, code in frames:
        lines += [f'  File "/app/{module}/{file}", line {lineno}, in {func}', f"    {code}"]
    return "\n".join(lines + [f"{error_type}: {message}"]) + "\n"


def record_error(span, error, timestamp):
    """Span status ERROR, error.type, and an OTel `exception` event."""
    error_type, message, trace_text = error
    span.set_status(Status(StatusCode.ERROR, f"{error_type}: {message}"))
    span.set_attribute("error.type", error_type)
    span.add_event("exception", {"exception.type": error_type, "exception.message": message,
                                 "exception.stacktrace": trace_text}, timestamp=timestamp)


def dependency_span(tracer, profile, parent_ctx, dependency, method, start_ns, duration_ns, error):
    if dependency == "kafka":
        topic = profile["topic"]
        name, kind_attrs = f"send {topic}", {
            "messaging.system": "kafka",
            "messaging.operation.type": "send",
            "messaging.operation.name": "send",
            "messaging.destination.name": topic,
            "server.address": "kafka-broker-0",
            "server.port": 9092,
        }
    else:
        table = profile["database"] + "_records"
        operation = "INSERT" if method == "POST" else "SELECT"
        name, kind_attrs = f"{operation} {table}", {
            "db.system.name": "postgresql",
            "db.system": "postgresql",  # older semantic-convention name
            "db.namespace": profile["database"],
            "db.operation.name": operation,
            "db.collection.name": table,
            "db.query.text": f"{operation} ... {table} WHERE id = $1",
            "server.address": "postgres-primary",
            "server.port": 5432,
        }
    span = tracer.start_span(name, context=parent_ctx, kind=SpanKind.CLIENT, start_time=start_ns, attributes=kind_attrs)
    if error:
        record_error(span, error, start_ns + duration_ns)
    span.end(end_time=start_ns + duration_ns)


def simulate_request(args, profile, tracer, logger, degraded):
    routes = profile["routes"]
    index = random.choices(range(len(routes)), weights=[r[2] for r in routes])[0]
    method, route, _weight, dependency = routes[index]
    primary = index == 0

    if degraded:
        p95 = args.degraded_p95_ms
        # Concentrate the new failures on the primary route while keeping the overall rate close to --degraded-error-rate.
        error_rate = min(1.0, args.degraded_error_rate / routes[0][2]) if primary else args.error_rate
    else:
        p95, error_rate = args.p95_ms, args.error_rate

    failed = random.random() < error_rate
    total_ms = latency_ms(p95)
    end_ns = time.time_ns()
    start_ns = end_ns - int(total_ms * 1e6)
    path = concrete_path(route)
    status_code = 500 if failed else (201 if method == "POST" else 200)

    server = tracer.start_span(f"{method} {route}", kind=SpanKind.SERVER, start_time=start_ns, attributes={
        "http.request.method": method,
        "http.route": route,
        "url.path": path,
        "url.scheme": "https",
        "server.address": f"{args.service}.{SERVICE_NAMESPACE}.internal",
        "network.protocol.version": "1.1",
        "http.response.status_code": status_code,
    })
    ctx = trace.set_span_in_context(server)

    # Dependency call inside the request: starts after 10-30% of the time, takes 30-60% of it.
    dep_start = start_ns + int(total_ms * random.uniform(0.1, 0.3) * 1e6)
    dep_duration = int(total_ms * random.uniform(0.3, 0.6) * 1e6)
    error = dep_error = None
    if failed and degraded and primary:
        # The latent bug lives in the service's own code; the dependency call succeeds.
        error_type, message = profile["bug"]
        error = (error_type, message, stacktrace(args.service, error_type, message, [HANDLER_FRAME, BUG_FRAME]))
    elif failed:
        # An ordinary failure: the dependency call fails and the request returns 500.
        error_type, message = random.choice(TRANSIENT_ERRORS)
        error = dep_error = (error_type, message, stacktrace(args.service, error_type, message, [HANDLER_FRAME, DEPENDENCY_FRAMES[dependency]]))
    dependency_span(tracer, profile, ctx, dependency, method, dep_start, dep_duration, dep_error)
    if error:
        record_error(server, error, end_ns)
    server.end(end_time=end_ns)

    log_attrs = {"http.request.method": method, "http.route": route, "url.path": path, "http.response.status_code": status_code}
    if error:
        log_attrs["error.type"] = error[0]
        logger.emit(timestamp=end_ns, context=ctx, severity_number=SeverityNumber.ERROR, severity_text="ERROR",
                    body=f"{method} {path} failed with {status_code}: {error[0]}: {error[1]}", attributes=log_attrs)
    else:
        logger.emit(timestamp=end_ns, context=ctx, severity_number=SeverityNumber.INFO, severity_text="INFO",
                    body=f"{method} {path} completed with {status_code} in {total_ms:.0f} ms", attributes=log_attrs)
    return failed, total_ms


def main():
    args = parse_args()
    profile = SERVICES.get(args.service, GENERIC)
    tracer_provider, logger_provider, tracer, logger, span_exporter, log_exporter = build_pipeline(args)

    stop = {"signal": None}

    def request_stop(signum, _frame):
        stop["signal"] = signal.Signals(signum).name

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    print(f"traffic: service={args.service} version={args.version} env={args.deployment_environment} rps={args.rps} "
          f"error_rate={args.error_rate} p95_ms={args.p95_ms} duration={args.duration or 'forever'} "
          f"degrade_after={args.degrade_after} degraded_error_rate={args.degraded_error_rate} "
          f"degraded_p95_ms={args.degraded_p95_ms} run_id={args.run_id}", flush=True)

    started = time.monotonic()
    next_request = started
    next_heartbeat = started + HEARTBEAT_SECONDS
    total = errors = 0
    window_latencies, window_errors = [], 0
    announced_degraded = False

    while stop["signal"] is None:
        now = time.monotonic()
        elapsed = now - started
        if args.duration and elapsed >= args.duration:
            break
        degraded = args.degrade_after is not None and elapsed >= args.degrade_after
        if degraded and not announced_degraded:
            print(f"traffic: {args.service} {args.version} degraded after {elapsed:.0f}s "
                  f"(error_rate={args.degraded_error_rate}, p95_ms={args.degraded_p95_ms})", flush=True)
            announced_degraded = True

        if now >= next_request:
            failed, ms = simulate_request(args, profile, tracer, logger, degraded)
            total += 1
            errors += failed
            window_errors += failed
            window_latencies.append(ms)
            next_request += random.expovariate(args.rps)  # Poisson arrivals
            if next_request < now - 1:  # fell far behind (e.g. laptop sleep): do not burst
                next_request = now
            continue

        if now >= next_heartbeat:
            n = len(window_latencies)
            p95 = sorted(window_latencies)[int(0.95 * (n - 1))] if n else 0
            print(f"heartbeat: t={elapsed:.0f}s mode={'degraded' if degraded else 'baseline'} requests={total} errors={errors} "
                  f"window_rps={n / HEARTBEAT_SECONDS:.2f} window_error_rate={(window_errors / n if n else 0):.4f} "
                  f"window_p95_ms={p95:.0f} spans_exported={span_exporter.ok} spans_failed={span_exporter.failed} "
                  f"logs_exported={log_exporter.ok} logs_failed={log_exporter.failed}", flush=True)
            window_latencies, window_errors = [], 0
            next_heartbeat += HEARTBEAT_SECONDS

        # Sleep until the next event, but wake at least every 250 ms to notice a stop signal.
        time.sleep(max(0.0, min(next_request, next_heartbeat, now + 0.25) - time.monotonic()))

    reason = stop["signal"] or "duration reached"
    tracer_provider.force_flush(30000)
    logger_provider.force_flush(30000)
    tracer_provider.shutdown()
    logger_provider.shutdown()
    print(f"traffic: stopped ({reason}) requests={total} errors={errors} spans_exported={span_exporter.ok} "
          f"spans_failed={span_exporter.failed} logs_exported={log_exporter.ok} logs_failed={log_exporter.failed}", flush=True)
    return 0 if (span_exporter.failed == 0 and log_exporter.failed == 0) else 1


if __name__ == "__main__":
    sys.exit(main())
