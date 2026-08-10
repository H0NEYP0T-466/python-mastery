# Logging and Monitoring

## What it is
Logging records what happened in your application. Monitoring observes the health and performance of your running system. Together, they form observability — the ability to understand what's happening inside your system without reproducing the issue. This file covers structured logging, log levels, log aggregation, metrics (Prometheus), distributed tracing (OpenTelemetry), health checks, and the difference between logging, metrics, and tracing — the three pillars of observability.

## Why it matters
Without observability, you're flying blind. A production error without logs is a mystery. A performance degradation without metrics is a guessing game. A distributed request failure without tracing is impossible to debug. In interviews, observability questions test whether you understand the three pillars, how to instrument an API, and what to monitor. For your work — ML serving where latency, throughput, and error rates directly impact user experience and cost — observability is not optional.

## Core example

### The three pillars of observability

```python
# 1. LOGGING — discrete events, what happened
# "User 123 requested /predict at 12:00:00, returned 200 in 450ms"
# Use: debugging specific errors, audit trails, forensic analysis

# 2. METRICS — numerical measurements over time, how the system is doing
# "P99 latency: 500ms, Error rate: 0.1%, Throughput: 100 req/s"
# Use: alerting, dashboards, capacity planning, trend analysis

# 3. TRACING — request flow across services, where time was spent
# "Request → API (10ms) → Auth (5ms) → Model (450ms) → Response"
# Use: distributed debugging, latency breakdown, service dependencies

# The relationship:
# Metrics tell you SOMETHING is wrong (high latency).
# Logs tell you WHAT happened (specific error).
# Tracing tells you WHERE it happened (which service/operation).

# All three are needed for complete observability.
```

### Structured logging — JSON logs for production

```python
import logging
import logging.config
import json
from pythonjsonlogger import jsonlogger

# Structured logging: every log line is a JSON object with fields.
# This allows log aggregation tools (ELK, Datadog, Splunk) to parse,
# filter, and query logs efficiently.

LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "()": jsonlogger.JsonFormatter,
            "format": "%(asctime)s %(name)s %(levelname)s "
                      "%(request_id)s %(user_id)s %(message)s "
                      "%(status_code)s %(duration_ms)s %(endpoint)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
            "level": "INFO",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
}

logging.config.dictConfig(LOGGING_CONFIG)
logger = logging.getLogger(__name__)

# Usage with structured fields:
logger.info(
    "Request processed",
    extra={
        "request_id": "abc-123",
        "user_id": 42,
        "endpoint": "/predict",
        "status_code": 200,
        "duration_ms": 450,
    }
)

# Output (JSON):
# {
#   "asctime": "2024-01-01 12:00:00,000",
#   "name": "app.api.predict",
#   "levelname": "INFO",
#   "request_id": "abc-123",
#   "user_id": 42,
#   "message": "Request processed",
#   "status_code": 200,
#   "duration_ms": 450,
#   "endpoint": "/predict"
# }

# The key: every log line has the same fields. Log aggregation tools
# can filter by user_id, endpoint, status_code, etc. This is vastly
# more powerful than grep-ing through text logs.
```

### Request ID middleware — correlation across logs

```python
import uuid
from fastapi import Request

# Every request gets a unique ID. All logs for that request include
# the ID. When debugging, you filter logs by request_id to see the
# full journey of a single request through the system.

class RequestIDMiddleware:
    def __init__(self, app):
        self.app = app
    
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        
        # Get ID from header (for tracing across services) or generate
        request_id = dict(scope["headers"]).get(b"x-request-id")
        if request_id:
            request_id = request_id.decode()
        else:
            request_id = str(uuid.uuid4())
        
        # Store in request state for endpoints/middleware to access
        # In FastAPI, we need to attach to the ASGI scope
        scope["state"] = scope.get("state", {})
        scope["state"]["request_id"] = request_id
        
        # Also inject into logging context
        # Using a contextvar or thread-local for the logger
        request_id_context.set(request_id)
        
        # Add to response headers
        async def modified_send(message):
            if message["type"] == "http.response.start":
                headers = message.get("headers", [])
                headers.append((b"x-request-id", request_id.encode()))
                message["headers"] = headers
            await send(message)
        
        await self.app(scope, receive, modified_send)

# In FastAPI middleware (simpler):
@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    request.state.request_id = request_id
    
    # Inject into logging context
    set_logging_context(request_id=request_id)
    
    response = await call_next(request)
    response.headers["x-request-id"] = request_id
    
    return response

# In endpoint:
@app.get("/predict/")
async def predict(request: Request):
    logger.info(
        "Prediction requested",
        extra={"request_id": request.state.request_id},
    )
    # ...
```

### Metrics with Prometheus — the standard for FastAPI

```python
from fastapi import FastAPI
from prometheus_client import Counter, Histogram, Gauge
from prometheus_fastapi_instrumentator import Instrumentator
import time

app = FastAPI()

# Option 1: Use prometheus-fastapi-instrumentator (recommended)
# Auto-instrumentation — collects standard metrics out of the box

Instrumentator().instrument(app).expose(app)

# This automatically adds:
# - http_requests_total (counter, by method, endpoint, status)
# - http_request_size_bytes (histogram)
# - http_response_size_bytes (histogram)
# - http_request_duration_seconds (histogram, by endpoint)

# Metrics endpoint: GET /metrics (Prometheus scrapes this)

# Option 2: Custom metrics for business-specific tracking

# Counter — monotonic increasing (requests, errors, events)
prediction_counter = Counter(
    "predictions_total",
    "Total number of predictions made",
    ["model", "status"],  # Labels for filtering
)

# Histogram — distribution of values (latency, sizes)
prediction_latency = Histogram(
    "prediction_latency_seconds",
    "Prediction latency in seconds",
    ["model"],
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, float("inf")],
)

# Gauge — instantaneous value (queue size, active connections)
active_connections = Gauge(
    "active_connections",
    "Number of active WebSocket connections",
)

# Usage in endpoint:
@app.post("/predict/")
async def predict(request: Request):
    start = time.perf_counter()
    model_name = "dinov2"
    
    try:
        result = await run_inference(request)
        prediction_counter.labels(model=model_name, status="success").inc()
        return result
    except Exception as e:
        prediction_counter.labels(model=model_name, status="error").inc()
        raise
    finally:
        duration = time.perf_counter() - start
        prediction_latency.labels(model=model_name).observe(duration)

# Prometheus configuration (prometheus.yml):
# scrape_configs:
#   - job_name: 'fastapi-api'
#     static_configs:
#       - targets: ['api:8000']
#     metrics_path: /metrics

# Grafana dashboard: query Prometheus to visualize:
# - Rate of requests (rate(http_requests_total[5m]))
# - P95/P99 latency (histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m])))
# - Error rate (rate(http_requests_total{status=~"5.."}[5m]) / rate(http_requests_total[5m]))
```

### Health checks — liveness and readiness

```python
from fastapi import FastAPI, status
from fastapi.responses import JSONResponse
import asyncio

app = FastAPI()

# Liveness check — is the process alive?
# If this fails, the orchestrator (Kubernetes, Docker) restarts the process.
@app.get("/health/live", status_code=status.HTTP_200_OK)
async def liveness():
    return {"status": "alive"}

# Readiness check — is the process ready to serve traffic?
# If this fails, the orchestrator stops sending traffic but doesn't restart.
# Used for: database connectivity, cache connectivity, model loading readiness.

@app.get("/health/ready")
async def readiness():
    checks = {}
    
    # Database check
    try:
        await db.check_connection()
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {str(e)}"
    
    # Redis check
    try:
        await redis_client.ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {str(e)}"
    
    # Model check
    try:
        if not model.is_loaded:
            checks["model"] = "not loaded"
        else:
            checks["model"] = "ok"
    except Exception as e:
        checks["model"] = f"error: {str(e)}"
    
    # If any check fails, return 503 (service unavailable)
    all_ok = all(v == "ok" for v in checks.values())
    status_code = status.HTTP_200_OK if all_ok else status.HTTP_503_SERVICE_UNAVAILABLE
    
    return JSONResponse(status_code=status_code, content={"status": "ready" if all_ok else "not_ready", "checks": checks})

# Startup check — block readiness until model is loaded
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load model on startup
    await model.load()
    
    # Warm up cache, connect to DB, etc.
    await db.connect()
    await redis_client.connect()
    
    yield  # App is running
    
    # Shutdown
    await model.unload()
    await db.disconnect()

app = FastAPI(lifespan=lifespan)

# Kubernetes deployment uses both:
# livenessProbe:
#   httpGet:
#     path: /health/live
#     port: 8000
#   initialDelaySeconds: 30
#   periodSeconds: 10
# readinessProbe:
#   httpGet:
#     path: /health/ready
#     port: 8000
#   initialDelaySeconds: 5
#   periodSeconds: 5

# Key difference: liveness = "restart me if I'm dead". Readiness
# = "stop sending traffic if I'm not ready". A process can be
# alive (liveness passes) but not ready (readiness fails) — e.g.,
# loading a large model. Don't restart it, just don't send traffic.
```

### Distributed tracing with OpenTelemetry

```python
# Distributed tracing follows a request across service boundaries.
# Each service adds a span to the trace. The trace ID is propagated
# via headers (traceparent, tracestate) across services.

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

# Configure tracing provider
trace.set_tracer_provider(TracerProvider())

# Export traces to Jaeger, Tempo, or other OTLP-compatible backend
otlp_exporter = OTLPSpanExporter(endpoint="http://jaeger:4317")
trace.get_tracer_provider().add_span_processor(
    BatchSpanProcessor(otlp_exporter)
)

# Instrument FastAPI app
FastAPIInstrumentor.instrument_app(app)

# Instrument outgoing HTTP calls (so traces propagate to downstream services)
HTTPXClientInstrumentor.instrument()

# Now, every request creates a trace with spans:
# - HTTP request received (span)
# - Auth middleware (span)
# - Database query (span)
# - Model inference (span)
# - HTTP response sent (span)

# The trace ID is propagated via headers:
# traceparent: 00-4bf92f3577b34da6a3ce929d0e0e4731-00f067aa0ba902b7-01
#   version-trace_id-parent_id-flags

# When your API calls another service, the trace ID is included
# in the outgoing request headers. The downstream service continues
# the same trace. The result: a single trace spans multiple services,
# showing the full request journey.

# In Jaeger/Tempo UI:
# You see a flame graph of the trace — each span is a bar showing
# duration. You can see which service/operation took the most time,
# where errors occurred, and the causal relationship between spans.

# For ML serving: trace the full pipeline:
# API receives request → preprocess → model inference → postprocess
# → response. Each step is a span. If inference is slow, you see it.
# If preprocessing is the bottleneck, you see it.
```

### Alerting — when to alert and what to alert on

```python
# Alerting rules (Prometheus / Grafana Alertmanager):

# 1. High error rate — alert if > 5% of requests are 5xx
# ALERT HighErrorRate
#   IF rate(http_requests_total{status=~"5.."}[5m]) / rate(http_requests_total[5m]) > 0.05
#   FOR 5m
#   LABELS {severity = "critical"}
#   ANNOTATIONS {
#     summary = "High error rate on {{$labels.job}}",
#     description = "Error rate is {{$value}}% for the last 5 minutes"
#   }

# 2. High latency — alert if P99 > 2s
# ALERT HighLatency
#   IF histogram_quantile(0.99, rate(http_request_duration_seconds_bucket[5m])) > 2
#   FOR 5m
#   LABELS {severity = "warning"}
#   ANNOTATIONS {
#     summary = "High latency on {{$labels.job}}",
#     description = "P99 latency is {{$value}}s for the last 5 minutes"
#   }

# 3. Service down — alert if no metrics scraped
# ALERT ServiceDown
#   IF up{job="fastapi-api"} == 0
#   FOR 1m
#   LABELS {severity = "critical"}
#   ANNOTATIONS {
#     summary = "Service {{$labels.job}} is down",
#     description = "The service has been down for more than 1 minute"
#   }

# 4. High memory usage — alert if > 80%
# ALERT HighMemoryUsage
#   IF process_resident_memory_bytes / process_virtual_memory_bytes > 0.8
#   FOR 5m
#   LABELS {severity = "warning"}
#   ANNOTATIONS {
#     summary = "High memory usage on {{$labels.job}}",
#     description = "Memory usage is {{$value * 100}}%"
#   }

# 5. Model health — alert if inference latency spikes
# ALERT HighInferenceLatency
#   IF histogram_quantile(0.95, rate(prediction_latency_seconds_bucket[5m])) > 5
#   FOR 3m
#   LABELS {severity = "warning"}
#   ANNOTATIONS {
#     summary = "High inference latency for {{$labels.model}}",
#     description = "P95 inference latency is {{$value}}s"
#   }

# Alerting principles:
# - Alert on symptoms, not causes (high latency, not "CPU is high")
# - Use multi-window conditions to avoid flapping (5m window, 5m duration)
# - Different severity levels: critical (page on-call), warning (ticket)
# - Every alert should have a clear action — if you don't know what
#   to do when an alert fires, don't alert on it
# - Avoid alert fatigue — too many alerts = ignored alerts
# - Test your alerts — break something in staging and verify the alert fires
```

## Common mistakes / gotchas

- **Logging sensitive data** — passwords, tokens, PII in logs is a security violation. Never log request bodies that contain sensitive data. Use structured logging with field-level redaction.
- **Logging at DEBUG in production** — DEBUG logs are verbose and can expose internal state. Use INFO for production. Have a way to dynamically enable DEBUG for specific modules when debugging.
- **Not using structured logs** — text logs are impossible to query at scale. Always use JSON logs in production. The extra parsing cost is negligible compared to the debugging benefit.
- **No request correlation** — without a request_id, you can't trace a single request through multiple services. Always generate and propagate a request ID.
- **Metrics without alerts** — metrics you don't alert on are just decoration. Define SLOs (Service Level Objectives) and alert when they're violated.
- **Alerting on everything** — alert fatigue is real. If you get paged at 3AM for something that can wait until morning, your alerting is broken. Be selective.
- **Not sampling traces** — full tracing on every request generates massive data. Sample (e.g., 1% of requests, or all errors) to keep tracing costs manageable.
- **Liveness probe that checks health** — if your liveness probe checks database connectivity and the DB is down, Kubernetes restarts your app repeatedly (crash loop). Liveness should only check if the process is alive. Readiness checks connectivity.

## Practice

> [!question]- Q1. Design an observability stack for a FastAPI ML inference API deployed on Kubernetes with 5 replicas. The stack needs: logging, metrics, tracing, alerting, and dashboards. Show the architecture and explain each component.
**Answer:** Architecture:
```
FastAPI (5 replicas)
  │
  ├─→ Logs: structured JSON → Fluent Bit (agent) → Loki (storage) → Grafana (query)
  ├─→ Metrics: Prometheus client → Prometheus (scrape) → Grafana (dashboards + alerts)
  ├─→ Tracing: OpenTelemetry → Tempo (storage) → Grafana (trace visualization)
  └─→ Health: /health/live, /health/ready → Kubernetes probes
  
Alertmanager
  │
  ├─→ PagerDuty (critical alerts — page on-call)
  ├─→ Slack (warning alerts — channel notification)
  └─→ Email (info alerts — daily digest)
```
Fluent Bit: lightweight log agent on each node, ships logs to Loki. Loki: log storage optimized for structured logs, low cost. Prometheus: metrics storage, scrapes /metrics endpoint from each replica every 15s. Tempo: trace storage, receives OTLP traces from FastAPI. Grafana: unified dashboard for logs, metrics, and traces. Alertmanager: routes alerts based on severity. Kubernetes liveness/ready probes: manage pod lifecycle. The key design: all three pillars (logs, metrics, traces) are queryable from Grafana. You can click on a metric spike → see the related traces → filter logs by trace ID. This unified observability is the gold standard.

> [!question]- Q2. Your FastAPI API's P99 latency spikes from 200ms to 5s every day at 2 AM for exactly 10 minutes. No errors, no traffic change. Design the investigation approach using observability tools.
**Answer:** Step 1: Check metrics at 2 AM — look at all metrics (CPU, memory, disk I/O, network, DB connections, cache hit rate, queue depth). The spike happens at a specific time — look for cron jobs, scheduled tasks, backups, or batch jobs that run at 2 AM. Step 2: Check traces at 2 AM — filter traces during the latency spike. Look at the trace waterfall: which span increased in duration? If it's the model inference span, the model is slower. If it's the DB span, the DB is slower. If it's a new span, something new is running. Step 3: Check logs at 2 AM — filter logs for WARNING/ERROR during the spike. Look for messages about "slow query", "cache miss", "model reload", "backup started". Step 4: Correlate with infrastructure — check if any infrastructure events happen at 2 AM: cron jobs, log rotation, database backups, certificate renewals, model updates, cache clearing. Step 5: Compare with normal traces — take a trace from normal time and a trace from spike time. Compare span durations. The difference identifies the bottleneck. Most likely cause: a scheduled job (database backup, log rotation, model update, cache rebuild) that competes for resources. Fix: move the job to a different time, isolate resources, or optimize the job.

> [!question]- Q3. Explain the difference between a metric, a log, and a trace. Give an example of each in the context of a FastAPI ML inference API. When would you query each one?
**Answer:** Metric: a numerical measurement at a point in time or over a window. Example: `prediction_latency_seconds{model="dinov2"} P99 = 450ms`. You query metrics to answer "how is the system performing?" — dashboards, alerting, capacity planning, trend analysis. Metrics are aggregated — you lose individual request details but gain a system-level view. Log: a discrete event with a timestamp and structured fields. Example: `{"timestamp": "12:00:00", "level": "ERROR", "request_id": "abc-123", "user_id": 42, "endpoint": "/predict", "error": "CUDA out of memory"}`. You query logs to answer "what exactly happened?" — debugging specific errors, audit trails, forensic analysis. Logs are detailed — you have full context for individual events but can't easily see system-level patterns. Trace: a collection of spans that represent a single request's journey through the system. Example: trace ID `xyz-789` with spans: API (5ms) → Auth (10ms) → Preprocess (50ms) → Inference (400ms) → Postprocess (20ms). You query traces to answer "where did the time go?" — distributed debugging, latency breakdown, service dependencies. Traces connect the dots across services — you see the causal flow of a single request. The relationship: a metric tells you latency is high. A trace shows you which operation is slow. A log tells you the specific error that occurred. You use all three together.

> [!question]- Q4. You need to add monitoring to a FastAPI API that's already in production. The team is worried about performance impact. Quantify the overhead of metrics, logging, and tracing, and recommend a rollout plan.
**Answer:** Overhead: Metrics (Prometheus client): negligible (~0.1-1ms per request). The client just increments counters and records histograms in-memory. The /metrics endpoint is scraped every 15-30s by Prometheus. No network overhead per request. Logging (structured, async): ~0.5-2ms per request if using async logging (QueueHandler). Synchronous logging adds ~2-5ms per request but is still negligible for most APIs. The bigger concern is log volume, not per-request overhead. Tracing (OpenTelemetry): ~1-5ms per request for span creation. The bigger concern is trace export volume — sending traces to the backend adds network overhead. Use batch export (every 1s or 5000 spans) to amortize the cost. Sampling (1% of requests) reduces overhead by 99x. Rollout plan: Phase 1 — Add metrics first (lowest risk, highest value). Deploy, verify /metrics endpoint works, configure Prometheus scrape. No code changes needed beyond adding the instrumentator. Phase 2 — Add structured logging. Switch from print/text logs to JSON logs. Add request_id middleware. Deploy to one replica, verify logs appear in the log aggregator. Phase 3 — Add tracing. Start with 1% sampling. Deploy to one replica, verify traces appear in the tracing backend. Increase sampling if needed. Phase 4 — Add alerting. Start with critical alerts only (service down, high error rate). Gradually add more alerts as you learn what's normal. The key: add one pillar at a time, measure overhead, verify value before adding the next.

> [!question]- Q5. A FastAPI API returns 500 errors intermittently. The error rate is 0.1% — too low to notice in real-time but users are complaining. The logs don't show any errors. Design the debugging approach.
**Answer:** Step 1: Verify the error is real — check metrics (http_requests_total{status="500"}) to confirm the 500s are happening and not a client-side issue. Check if the 500s are from specific endpoints, users, or times. Step 2: Enable more verbose logging — if the current log level is INFO, temporarily set to DEBUG for the failing endpoint. But at 0.1% error rate, you'd need to capture a lot of logs. Better: add error-specific logging — log the full exception and request context whenever a 500 occurs. Step 3: Add distributed tracing — if the API calls other services (DB, cache, external API), the 500 might be from a downstream service. Tracing shows which service is failing. Step 4: Add correlation — ensure every 500 response includes a request_id. Ask affected users for the request_id (or check client-side logs). Filter server logs by that request_id. Step 5: Reproduce — if the 500 is correlated with specific inputs, try to reproduce locally with those inputs. If it's intermittent and not reproducible, it's likely a race condition, resource exhaustion, or external service issue. Add defensive logging around the suspected code paths. Step 6: Use metrics to find patterns — break down 500s by endpoint, user, time, model version. If 500s only happen with a specific model version, the issue is in that model. If only at certain times, it's resource-related. The key: at 0.1% error rate, you need automated detection (metrics + alerting on error rate threshold) and rich context (tracing + structured logs) to catch and debug the issue. Don't rely on manual log searching — it won't find 0.1% errors.

## Related
[[logging]]
[[performance-profiling]]
[[middleware]]
[[error-handling-and-exception-handlers]]
[[rate-limiting]]
[[caching]]

#status/new