# Deployment — Docker + Uvicorn

## What it is
Deploying a FastAPI API means packaging it, running it with an ASGI server (uvicorn), and making it accessible to clients. The standard approach: Docker container with uvicorn (or gunicorn + uvicorn workers), behind a reverse proxy (nginx) for TLS and static files, with process management and health checks. This file covers Docker best practices, uvicorn configuration, worker models, graceful shutdown, TLS termination, and the difference between development and production deployment.

## Why it matters
A FastAPI app that works locally but fails in production is useless. Deployment issues — wrong worker count, no graceful shutdown, missing health checks, improper TLS — cause downtime, data loss, and security vulnerabilities. In interviews, deployment questions test whether you understand containerization, process management, and production hardening. For your work — deploying ML models that need to be available 24/7 — deployment is the difference between a demo and a service.

## Core example

### Dockerfile — the production-grade version

```dockerfile
# Stage 1: Build — install dependencies
FROM python:3.12-slim AS builder

WORKDIR /build

# Install system dependencies for building Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (layer caching)
COPY requirements.txt .
COPY pyproject.toml .

# Install Python dependencies in a single layer
# --no-cache-dir avoids bloating the image
# --no-deps if you're using a lock file with all deps
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Stage 2: Runtime — minimal image
FROM python:3.12-slim

# Run as non-root user (security best practice)
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser

WORKDIR /app

# Copy installed packages from builder stage
COPY --from=builder /usr/local/lib/python3.12 /usr/local/lib/python3.12
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY --chown=appuser:appuser . .

# Switch to non-root user
USER appuser

# Environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    WORKERS=4

# Health check (used by Docker and orchestration)
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.request('http://localhost:8000/health/ready')"] \
    || exit 1

# Expose port
EXPOSE 8000

# Run uvicorn with gunicorn for production
# gunicorn manages workers, uvicorn handles ASGI
CMD ["gunicorn", "main:app", "--workers", "4", "--worker-class", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000", "--timeout", "30", "--graceful-timeout", "30"]
```

### Why this Dockerfile is structured this way

```python
# Multi-stage build: builder + runtime
# The builder stage installs dependencies. The runtime stage
# copies only what's needed. The result is a smaller image
# (no build tools, no source files from builder).

# Non-root user: security
# Running as root in containers is dangerous. If the app is
# compromised, the attacker has root. The appuser has minimal
# permissions. /sbin/nologin prevents shell access.

# PYTHONDONTWRITEBYTECODE=1: don't write .pyc files
# In containers, .pyc files are unnecessary and add clutter.

# PYTHONUNBUFFERED=1: don't buffer stdout/stderr
# Python buffers output by default. In containers, this means
# logs don't appear in real-time. Unbuffered = immediate logs.

# HEALTHCHECK: Docker-native health check
# Docker uses this to determine if the container is healthy.
# Used by docker-compose and orchestration platforms.
# If health check fails repeatedly, the container is restarted.

# gunicorn + uvicorn worker model:
# gunicorn is the process manager — it spawns and manages workers.
# uvicorn is the ASGI server — it handles HTTP requests.
# Each worker is a separate process with its own event loop.
# This is the recommended production setup for CPU-bound workloads.

# Alternative: uvicorn directly (simpler, fewer features)
# CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
# Use this for development or simple deployments.
# For production with multiple workers, use gunicorn.
```

### Uvicorn configuration — dev vs prod

```python
# Development — single process, auto-reload
# $ uvicorn main:app --reload --host 0.0.0.0 --port 8000
# --reload: auto-restart on code changes (development only)
# Not for production — it's single-threaded and slow.

# Production — multiple workers
# $ uvicorn main:app --workers 4 --host 0.0.0.0 --port 8000
# --workers: number of worker processes (one per CPU core)
# Each worker has its own event loop and memory space.
# Requests are distributed across workers by the OS.

# Production with gunicorn (recommended for ML serving):
# $ gunicorn main:app \
#   --workers 4 \
#   --worker-class uvicorn.workers.UvicornWorker \
#   --bind 0.0.0.0:8000 \
#   --timeout 30 \
#   --graceful-timeout 30

# Key uvicorn flags:
# --host: bind address (0.0.0.0 = all interfaces)
# --port: port to listen on
# --workers: worker processes (only works with gunicorn or uvicorn --workers)
# --timeout: max seconds before a request is killed (default: 30)
# --graceful-timeout: seconds to wait for requests to finish on shutdown
# --limit-concurrency: max concurrent connections per worker
# --limit-max-requests: restart worker after N requests (prevent memory leaks)
# --proxy-headers: trust X-Forwarded-* headers (behind reverse proxy)
# --forwarded-allowed-ips: which proxy IPs to trust (security)

# Worker count calculation:
# For I/O-bound APIs (CRUD, external API calls):
# workers = (2 * CPU_cores) + 1  (standard gunicorn recommendation)
# For CPU-bound APIs (ML inference):
# workers = CPU_cores  (one per core, each loads the model)
# But: each worker loads the model into memory. 4 workers = 4x model memory.
# For large models (DINOv2, LLMs), use 1-2 workers and offload inference
# to a separate service.

# Memory consideration:
# If each worker uses 2GB (model + overhead) and you have 8GB RAM:
# max_workers = 8GB / 2GB = 4 workers
# Leave 1-2GB for OS and other processes.
# So: 3 workers for 8GB RAM with 2GB per worker.
```

### Graceful shutdown — handling SIGTERM

```python
# When Kubernetes or Docker stops a container, it sends SIGTERM.
# The app should: stop accepting new requests, finish existing
# requests within the timeout, then exit.

# Uvicorn handles this automatically with --graceful-timeout.
# But you need to handle cleanup in your code.

import asyncio
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: load model, connect to DB, etc.
    await model.load()
    await db.connect()
    await redis_client.connect()
    
    yield  # App is running
    
    # Shutdown: graceful cleanup
    # This is called when SIGTERM is received
    
    # 1. Stop accepting new requests
    # (handled by uvicorn — it stops the listener)
    
    # 2. Wait for in-flight requests to complete
    # (handled by --graceful-timeout — uvicorn waits)
    
    # 3. Clean up resources
    await model.unload()  # Free GPU memory
    await db.disconnect()  # Close DB connections
    await redis_client.close()  # Close Redis connections
    
    # 4. Any other cleanup (flush logs, save state, etc.)
    await logger.flush()

app = FastAPI(lifespan=lifespan)

# In Kubernetes, the termination flow:
# 1. Kubernetes sends SIGTERM to the container
# 2. Uvicorn stops accepting new requests
# 3. In-flight requests continue (up to graceful-timeout)
# 4. Lifespan shutdown runs (cleanup)
# 5. Process exits
# 6. If process doesn't exit within terminationGracePeriodSeconds,
#    Kubernetes sends SIGKILL (force kill)

# Kubernetes deployment:
# terminationGracePeriodSeconds: 60  # Must be > graceful-timeout
# This gives uvicorn enough time to finish requests and clean up.
```

### Reverse proxy with nginx — TLS and static files

```nginx
# nginx.conf — production reverse proxy

upstream fastapi_backend {
    # If running multiple FastAPI instances (for high availability):
    server 127.0.0.1:8000;
    # server 127.0.0.1:8001;  # Additional instances
    keepalive 32;
}

server {
    listen 443 ssl http2;
    server_name api.myapp.com;
    
    # TLS certificates (Let's Encrypt)
    ssl_certificate /etc/letsencrypt/live/api.myapp.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.myapp.com/privkey.pem;
    
    # TLS security settings
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;
    
    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    
    # Max request size (for file uploads)
    client_max_body_size 100M;
    
    # Request timeout
    proxy_read_timeout 300s;  # For long-running inference
    proxy_connect_timeout 5s;
    proxy_send_timeout 300s;
    
    # Pass real client IP to FastAPI
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    
    # WebSocket support
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    
    # Health check endpoint (nginx plus only, or use external monitor)
    # location /health { proxy_pass http://fastapi_backend/health; }
    
    # API routes
    location / {
        proxy_pass http://fastapi_backend;
        proxy_intercept_errors on;  # Let FastAPI handle error pages
    }
    
    # Static files (if FastAPI serves them)
    location /static/ {
        alias /app/static/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }
    
    # API docs — disable in production or protect
    location /docs {
        # return 404;  # Disable in production
        # Or protect with auth:
        # auth_basic "Restricted";
        # auth_basic_user_file /etc/nginx/.htpasswd;
        proxy_pass http://fastapi_backend/docs;
    }
}

# HTTP → HTTPS redirect
server {
    listen 80;
    server_name api.myapp.com;
    return 301 https://$host$request_uri;
}
```

### Docker Compose — local development with all services

```yaml
# docker-compose.yml — full local development stack

version: "3.8"

services:
  api:
    build: .
    container_name: fastapi-api
    ports:
      - "8000:8000"
    environment:
      - ENVIRONMENT=development
      - DATABASE_URL=postgresql://dev:dev@db:5432/devdb
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
    volumes:
      - ./app:/app  # Live code reload (development only)
    command: uvicorn main:app --host 0.0.0.0 --port 8000 --reload

  db:
    image: postgres:16-alpine
    container_name: postgres-db
    environment:
      POSTGRES_DB: devdb
      POSTGRES_USER: dev
      POSTGRES_PASSWORD: dev
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U dev"]
      interval: 5s
      timeout: 5s
      retries: 5
    ports:
      - "5432:5432"  # Expose for local debugging

  redis:
    image: redis:7-alpine
    container_name: redis-cache
    command: redis-server --save 60 1 --loglevel warning
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 5s
      retries: 5
    ports:
      - "6379:6379"

  nginx:
    image: nginx:alpine
    container_name: nginx-proxy
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
      - ./certs:/etc/letsencrypt:ro  # TLS certificates
    depends_on:
      - api

volumes:
  postgres_data:
  redis_data:
```

### Kubernetes deployment — production orchestration

```yaml
# k8s/deployment.yaml

apiVersion: apps/v1
kind: Deployment
metadata:
  name: fastapi-api
spec:
  replicas: 3
  selector:
    matchLabels:
      app: fastapi-api
  template:
    metadata:
      labels:
        app: fastapi-api
    spec:
      containers:
        - name: api
          image: myregistry/fastapi-api:v1.2.3
          ports:
            - containerPort: 8000
          env:
            - name: ENVIRONMENT
              value: "production"
            - name: DATABASE_URL
              valueFrom:
                secretKeyRef:
                  name: app-secrets
                  key: database-url
            - name: JWT_SECRET_KEY
              valueFrom:
                secretKeyRef:
                  name: app-secrets
                  key: jwt-secret
          resources:
            requests:
              memory: "2Gi"
              cpu: "500m"
            limits:
              memory: "4Gi"
              cpu: "2000m"
          livenessProbe:
            httpGet:
              path: /health/live
              port: 8000
            initialDelaySeconds: 30
            periodSeconds: 10
          readinessProbe:
            httpGet:
              path: /health/ready
              port: 8000
            initialDelaySeconds: 5
            periodSeconds: 5
          terminationGracePeriodSeconds: 60
          lifecycle:
            preStop:
              exec:
                command: ["sleep", "30"]  # Give time for in-flight requests

---

apiVersion: v1
kind: Service
metadata:
  name: fastapi-api-service
spec:
  selector:
    app: fastapi-api
  ports:
    - protocol: TCP
      port: 80
      targetPort: 8000
  type: ClusterIP  # Internal service

---

apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: fastapi-api-ingress
  annotations:
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
    nginx.ingress.kubernetes.io/proxy-read-timeout: "300"
    nginx.ingress.kubernetes.io/proxy-body-size: "100m"
spec:
  tls:
    - hosts:
        - api.myapp.com
      secretName: api-tls-secret
  rules:
    - host: api.myapp.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: fastapi-api-service
                port:
                  number: 80
```

## Common mistakes / gotchas

- **Running uvicorn with --reload in production** --reload is for development only. It's single-threaded and has significant overhead. In production, use --workers or gunicorn.
- **Not setting --timeout for long-running endpoints** — uvicorn's default timeout is 30s. ML inference endpoints often take longer. Set --timeout 300 or higher. But also consider async long-running patterns (return job ID, poll for results).
- **Running as root in containers** — security risk. Always use a non-root user. If your app needs to write files, give that directory to the appuser.
- **No health checks** — without health checks, Kubernetes/Docker can't tell if your app is actually working. They only know if the process is running. Add both liveness and readiness probes.
- **Not handling graceful shutdown** — if the process is killed (SIGKILL) without cleanup, DB connections leak, GPU memory isn't freed, in-flight requests are dropped. Handle SIGTERM in lifespan and set appropriate terminationGracePeriodSeconds.
- **Too many workers for memory-constrained environments** — each worker loads the full model. 4 workers with a 2GB model = 8GB RAM. Calculate based on available memory. For large models, use 1 worker + model server or batch inference.
- **Exposing FastAPI docs in production** — /docs and /redoc expose your API schema and let anyone execute requests. Disable them in production (docs_url=None) or protect them with auth.
- **Not setting resource limits in Kubernetes** — without memory limits, a memory leak can exhaust the node. Without CPU limits, a CPU spike can starve other pods. Always set requests and limits.

## Practice

> [!question]- Q1. Your FastAPI ML inference API is deployed on Kubernetes with 3 replicas. Each replica loads a 3GB model. During a deployment, new pods start but old pods don't terminate, causing OOM kills. Diagnose and fix.
**Answer:** The issue is the deployment strategy and memory limits. During a rolling update, Kubernetes creates new pods before terminating old ones. With 3 replicas and 3GB models: old pods use 9GB, new pods use another 9GB = 18GB total during rollout. If the node has 16GB RAM, OOM kills occur. Fix: (1) Use `maxSurge: 0, maxUnavailable: 1` in the deployment strategy — this ensures Kubernetes terminates a pod before creating a new one, keeping total pods at 3 during rollout. (2) Set resource requests/limits accurately (4GB per pod = 3GB model + 1GB overhead). (3) Use `terminationGracePeriodSeconds: 60` with a preStop hook to give pods time to finish requests before termination. (4) Consider model sharing — use a separate model server that all replicas share, so only one copy of the model is loaded. Or use model quantization to reduce model size. The key: understand that rolling updates temporarily double your pod count. Size your cluster accordingly, or configure the deployment strategy to avoid simultaneous old+new pods.

> [!question]- Q2. Compare running FastAPI with uvicorn directly vs gunicorn + uvicorn workers. When would you use each, and what are the trade-offs?
**Answer:** uvicorn directly: `uvicorn main:app --workers 4`. Simpler, fewer dependencies. Uvicorn manages its own workers. But uvicorn's worker management is basic — no graceful reload, limited monitoring, fewer deployment features. Best for: simple deployments, development, single-service containers. gunicorn + uvicorn: `gunicorn main:app --workers 4 --worker-class uvicorn.workers.UvicornWorker`. gunicorn is a mature process manager with: graceful reload (SIGHUP), worker recycling (--max-requests), better logging, more deployment features, battle-tested in production. Trade-off: adds gunicorn as a dependency and a layer of process management. Best for: production deployments, environments that expect gunicorn (PaaS like Heroku, Render), when you need worker recycling to prevent memory leaks. Recommendation: use gunicorn + uvicorn for production, uvicorn directly for development. The added complexity is minimal and the operational benefits are significant. For Docker/Kubernetes, both work — gunicorn is the safer choice for production.

> [!question]- Q3. A FastAPI API behind nginx returns 502 Bad Gateway errors intermittently under load. The FastAPI logs show no errors. Diagnose and fix.
**Answer:** 502 Bad Gateway from nginx means nginx couldn't get a valid response from FastAPI. Causes: (1) **FastAPI workers exhausted** — all workers are busy handling requests. New requests queue up and eventually timeout. Fix: increase worker count or optimize endpoint latency. (2) **nginx proxy_read_timeout too short** — FastAPI is slow (e.g., ML inference taking 60s) but nginx times out at 30s. Fix: increase proxy_read_timeout to match your slowest endpoint. (3) **Keep-alive connection issues** — nginx keep-alive connections to FastAPI are closed but nginx tries to reuse them. Fix: configure keepalive in upstream and ensure FastAPI's keepalive settings match. (4) **FastAPI process crashed** — the process died but nginx didn't detect it. Fix: add health checks and ensure Kubernetes/Docker restarts the container. (5) **Connection limit reached** --uvicorn --limit-concurrency is too low, rejecting connections. Fix: increase limit or remove it. Diagnosis: check nginx error logs for the specific 502 cause (timeout vs connection refused vs upstream sent invalid response). Check FastAPI access logs — are requests reaching FastAPI? Check worker utilization — are all workers busy? Check response times — are endpoints timing out? The fix depends on the root cause, but the most common under load is worker exhaustion (need more workers or faster endpoints) or nginx timeout (need longer proxy_read_timeout).

> [!question]- Q4. You need to deploy a FastAPI API that serves a 5GB ML model. The API must handle 100 requests/minute with P99 latency under 5 seconds. Design the deployment architecture.
**Answer:** A 5GB model can't be loaded into each worker process without massive memory usage. Architecture: (1) **Model server pattern** — run the model in a separate service (TorchServe, Triton, or custom FastAPI model server) that loads the model once. The main FastAPI API calls the model server via HTTP or gRPC. This way, the model is loaded once, not per worker. (2) **GPU acceleration** — if the model runs on GPU, use GPU instances. The model server runs on GPU instances with Triton (optimized for GPU inference). The FastAPI API runs on CPU instances, forwarding inference requests to the GPU model server. (3) **Autoscaling** — the model server autoscales based on inference queue depth. The FastAPI API autoscales based on request rate. (4) **Caching** — cache inference results for repeated inputs (Redis cache with 24h TTL). This reduces model server load significantly if there are duplicate queries. (5) **Batching** — the model server supports dynamic batching — multiple inference requests are batched into a single GPU call. This improves throughput. (6) **Queue for long requests** — for requests that might exceed 5s, use an async pattern: accept request → return job ID → client polls for results. The 5s P99 target applies to the polling endpoint, not the inference itself. Key design: separate the API layer from the inference layer. The API handles auth, validation, caching, rate limiting. The model server handles inference. This separation allows independent scaling, deployment, and optimization of each layer.

> [!question]- Q5. Explain the difference between liveness probe and readiness probe in Kubernetes. Why do you need both? Give an example where one passes and the other fails.
**Answer:** Liveness probe: "Is the process alive?" If it fails, Kubernetes restarts the pod. It checks if the process is running and not deadlocked. Readiness probe: "Is the pod ready to serve traffic?" If it fails, Kubernetes stops sending traffic to the pod but doesn't restart it. It checks if the pod's dependencies are ready and the pod can handle requests. You need both because a process can be alive but not ready (e.g., loading a large model — the process is running but can't serve requests yet). Example: FastAPI API with a 5GB model. On startup, the process is alive (liveness probe passes — the process is running). But the model is still loading from disk (takes 30s). During this time, the readiness probe fails — the pod isn't ready to serve traffic. Kubernetes doesn't send requests to it. After 30s, the model is loaded, readiness probe passes, and Kubernetes starts sending traffic. If the model fails to load (corrupted file), the readiness probe keeps failing — the pod never receives traffic. But the liveness probe keeps passing — the process is alive, just not useful. Kubernetes doesn't restart it (because it's alive), but it also doesn't send traffic. If liveness failed instead, Kubernetes would restart the pod repeatedly (crash loop), which is wrong — the process isn't dead, it just can't serve. The key: liveness = restart me. Readiness = don't send traffic yet. Both are needed for correct deployment behavior.

## Related
[[env-and-config-management]]
[[logging-and-monitoring]]
[[project-folder-structure]]
[[inference-serving-patterns]]
[[system-design-for-apis-at-scale]]

#status/new