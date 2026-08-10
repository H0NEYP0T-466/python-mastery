# Middleware

## What it is
FastAPI middleware sits between the ASGI server (uvicorn) and your application, intercepting every request before it reaches routing and every response before it's sent back to the client. Middleware can modify requests and responses, short-circuit requests (return a response without calling the endpoint), add headers, log requests, handle CORS, authenticate, and measure timing. The middleware stack executes in a specific order (first-added, first-called for requests; reverse order for responses), and understanding this order is critical for correct middleware behavior. This file covers the middleware mechanics, the built-in middleware, custom middleware patterns, and the gotchas that cause middleware to silently break your API.

## Why it matters
Middleware is how you implement cross-cutting concerns that apply to every request: CORS, authentication, logging, rate limiting, compression, request timing. But misconfigured middleware is the #1 cause of "my API works locally but fails in production" (CORS), "my auth doesn't work on some routes" (middleware order), and "my responses are slow" (middleware doing I/O). In interviews, middleware questions test whether you understand the execution order, the difference between middleware and dependencies, and when to use each. For your work — building production APIs — middleware is unavoidable. Getting it right means your API is secure, observable, and performant.

## Core example

### Middleware execution order — the onion model

```python
from fastapi import FastAPI, Request
import time

app = FastAPI()

# Middleware is added in order — but executes like an onion:
# Request: A → B → C → endpoint
# Response: endpoint → C → B → A

@app.middleware("http")
async def middleware_a(request: Request, call_next):
    print("A: before")
    start = time.perf_counter()
    response = await call_next(request)  # Pass to next layer
    duration = time.perf_counter() - start
    print(f"A: after ({duration:.3f}s)")
    response.headers["X-Middleware-A"] = "added"
    return response

@app.middleware("http")
async def middleware_b(request: Request, call_next):
    print("B: before")
    response = await call_next(request)
    print("B: after")
    response.headers["X-Middleware-B"] = "added"
    return response

@app.get("/")
async def root():
    print("ENDPOINT")
    return {"message": "hello"}

# GET / output:
# A: before
# B: before
# ENDPOINT
# B: after
# A: after (0.005s)

# Key insights:
# 1. call_next() passes control to the next middleware or endpoint
# 2. Everything before call_next runs on the request path (IN)
# 3. Everything after call_next runs on the response path (OUT)
# 4. Response middleware runs in REVERSE order of request middleware
# 5. The outermost middleware (first added) sees the request first
#    and the response last — it wraps everything

# This is identical to the context manager pattern and decorator pattern.
# If you understand those, you understand middleware.
```

### CORS middleware — the most common production issue

```python
from fastapi.middleware.cors import CORSMiddleware

# CORS (Cross-Origin Resource Sharing) controls which domains can
# access your API. Browsers block cross-origin requests by default.
# CORS middleware adds the appropriate headers to allow or deny.

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://myapp.com",
        "https://admin.myapp.com",
    ],
    allow_credentials=True,  # Allow cookies/auth headers
    allow_methods=["*"],  # Or ["GET", "POST", "PUT", "DELETE"]
    allow_headers=["*"],  # Or ["Authorization", "Content-Type"],
    max_age=3600,  # Cache preflight requests for 1 hour
)

# CRITICAL: allow_origins=["*"] with allow_credentials=True is
# REJECTED by browsers. If you need credentials (cookies, auth headers),
# you MUST specify explicit origins — wildcards are not allowed.

# For development, you can allow all:
# allow_origins=["*"]  # Only if allow_credentials=False

# For production, ALWAYS specify exact origins:
# allow_origins=["https://myapp.com", "https://api.myapp.com"]

# CORS preflight (OPTIONS) requests:
# Before a cross-origin request with non-simple headers/methods, the
# browser sends an OPTIONS request to check if the server allows it.
# CORS middleware handles OPTIONS responses automatically — no endpoint
# needed. This is why you don't define OPTIONS routes in FastAPI.

# Common CORS errors:
# 1. "No 'Access-Control-Allow-Origin' header" — middleware not added
#    or origin not in allow_origins list
# 2. "Cannot allow credentials with wildcard origin" — allow_origins=["*"]
#    with allow_credentials=True. Fix: specify exact origins.
# 3. "Request header field X-Custom is not allowed by
#    Access-Control-Allow-Headers" — custom header not in allow_headers.
#    Fix: add it to allow_headers or use ["*"].
```

### Custom middleware — timing, logging, and request modification

```python
from fastapi import Request
import time
import uuid

# Timing middleware — measure request latency
@app.middleware("http")
async def timing_middleware(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration = time.perf_counter() - start
    response.headers["X-Response-Time"] = f"{duration*1000:.1f}ms"
    # Also log for monitoring
    logger.info(
        f"{request.method} {request.url.path} "
        f"{response.status_code} {duration*1000:.1f}ms"
    )
    return response

# Request ID middleware — correlation ID for tracing
@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    # Get ID from header or generate new one
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.request_id = request_id  # Store for endpoint access
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id  # Echo back
    return response

# Endpoint can access the request ID:
@app.get("/")
async def root(request: Request):
    return {"request_id": request.state.request_id}

# GZIP compression middleware — compress responses
from fastapi.middleware.gzip import GZipMiddleware
app.add_middleware(GZipMiddleware, minimum_size=1000)
# Compress responses over 1KB. Browsers automatically decompress.
# Saves 60-80% bandwidth for text responses (JSON, HTML, CSS).

# HTTPS redirect middleware — force HTTPS in production
@app.middleware("http")
async def https_redirect(request: Request, call_next):
    if request.headers.get("x-forwarded-proto") == "http":
        # Behind a reverse proxy that sets x-forwarded-proto
        url = request.url.replace(scheme="https")
        return RedirectResponse(url=url, status_code=301)
    return await call_next(request)
```

### Middleware vs dependencies — when to use which

```python
# Middleware and dependencies both run before endpoints, but they serve
# different purposes:

# Use MIDDLEWARE when:
# - You need to run code for EVERY request (including 404s, health checks)
# - You need to modify the request or response at the ASGI level
# - You need to handle CORS preflight (OPTIONS) requests
# - You need to measure total request time (including routing/validation)
# - You need to compress/decompress at the HTTP level
# - You need to run code before routing (e.g., block by IP before routing)

# Use DEPENDENCIES when:
# - You need to inject a value into the endpoint function
# - You need to run code only for specific routes (not all routes)
# - You need to raise HTTPException with a specific status code
# - You need to share logic across a group of routes (via APIRouter deps)
# - You need to test with dependency overrides
# - You need cleanup (yield pattern) tied to request lifecycle

# Key difference: middleware runs BEFORE routing (for request phase),
# so it applies to ALL requests including 404s. Dependencies run AFTER
# routing, so they only apply to matched routes.

# Example: auth as middleware vs dependency
# As middleware: every request (including /health, /docs, 404) goes through auth.
# You need to exempt public routes with path checks.
# As dependency: only routes with Depends(get_current_user) require auth.
# Public routes don't have the dependency — cleaner separation.

# Best practice: use dependencies for auth (per-route control), middleware
# for CORS, logging, timing, compression (truly cross-cutting).
```

### Middleware that short-circuits — returning without calling the endpoint

```python
from fastapi import Request, Response
from starlette.responses import JSONResponse

# Middleware can return a response without calling call_next().
# This "short-circuits" the request — the endpoint is never called.

# Maintenance mode middleware
MAINTENANCE_MODE = False

@app.middleware("http")
async def maintenance_mode(request: Request, call_next):
    global MAINTENANCE_MODE
    if MAINTENANCE_MODE:
        # Return a response without calling the endpoint
        return JSONResponse(
            status_code=503,
            content={"error": "Service under maintenance"},
        )
    return await call_next(request)

# IP blocking middleware
BLOCKED_IPS = {"1.2.3.4", "5.6.7.8"}

@app.middleware("http")
async def ip_blocker(request: Request, call_next):
    client_ip = request.client.host
    if client_ip in BLOCKED_IPS:
        return Response(status_code=403)  # Forbidden
    return await call_next(request)

# Rate limiting middleware (simplified)
from collections import defaultdict
import time

request_counts = defaultdict(list)

@app.middleware("http")
async def rate_limiter(request: Request, call_next):
    client_ip = request.client.host
    now = time.time()
    
    # Remove old entries (older than 1 minute)
    request_counts[client_ip] = [
        t for t in request_counts[client_ip] if now - t < 60
    ]
    
    if len(request_counts[client_ip]) > 100:
        return JSONResponse(
            status_code=429,
            content={"error": "Rate limit exceeded"},
        )
    
    request_counts[client_ip].append(now)
    return await call_next(request)

# The key: short-circuiting middleware returns a Response directly
# without awaiting call_next(). The request never reaches routing
# or the endpoint. This is useful for: maintenance mode, IP blocking,
# rate limiting, authentication (if you want it at middleware level),
# and any check that should reject requests before they reach your code.
```

### Stateful middleware — sharing data across the request lifecycle

```python
# Middleware can attach data to request.state, which is available
# throughout the request lifecycle (in other middleware, dependencies,
# and endpoints).

@app.middleware("http")
async def user_tier_middleware(request: Request, call_next):
    # Determine user tier from token or IP
    tier = await determine_tier(request)
    request.state.user_tier = tier  # Attach to request state
    response = await call_next(request)
    # Can also modify response based on tier
    if tier == "premium":
        response.headers["X-Tier"] = "premium"
    return response

# Endpoint accesses the state:
@app.get("/premium-feature/")
async def premium_feature(request: Request):
    if request.state.user_tier != "premium":
        raise HTTPException(403, "Premium only")
    return {"feature": "premium"}

# request.state is a simple namespace object — you can attach any
# attributes to it. The attributes exist only for the duration of
# the request and are not shared across requests. This is the standard
# pattern for passing data from middleware to endpoints without using
# global variables or dependency injection.

# Alternative: use dependencies instead of request.state for cleaner code.
# But request.state is useful when the data is needed by multiple
# middleware layers or when you want to avoid dependency chains.
```

### ASGI middleware vs HTTP middleware — the lower level

```python
from fastapi import FastAPI
from starlette.middleware.base import BaseHTTPMiddleware

# @app.middleware("http") is the high-level HTTP middleware.
# It works with Request and Response objects — convenient but
# has limitations (can't handle WebSockets, streaming issues).

# ASGI middleware is lower-level — it works with ASGI scope, receive, send.
# It handles ALL ASGI events (HTTP, WebSocket, lifespan).

class CustomASGIMiddleware:
    def __init__(self, app):
        self.app = app
    
    async def __call__(self, scope, receive, send):
        # scope: dict with type, method, path, headers, etc.
        # receive: awaitable that returns ASGI events
        # send: awaitable that sends ASGI events
        
        if scope["type"] == "http":
            # HTTP request
            # Can modify scope before passing to app
            scope["modified"] = True
            
            # Can intercept send to modify responses
            async def modified_send(message):
                if message["type"] == "http.response.start":
                    # Modify response headers
                    message["headers"].append((b"x-custom", b"value"))
                await send(message)
            
            await self.app(scope, receive, modified_send)
        else:
            # WebSocket or other ASGI type — pass through
            await self.app(scope, receive, send)

# Register ASGI middleware:
app.add_middleware(CustomASGIMiddleware)

# When to use ASGI middleware vs HTTP middleware:
# - HTTP middleware (@app.middleware("http")): for HTTP-only concerns,
#   easier to work with Request/Response objects.
# - ASGI middleware: for WebSocket support, lifespan events, or when
#   you need to modify the ASGI scope directly.
# - BaseHTTPMiddleware (starlette): a middle ground — gives you the
#   HTTP middleware interface but as a class. Useful for reusable
#   middleware packages.

# Gotcha with BaseHTTPMiddleware: it runs each request in a separate
# thread, which can cause issues with request.state and background
# tasks. For most cases, @app.middleware("http") is simpler and safer.
```

## Common mistakes / gotchas

- **CORS with credentials and wildcard origin** — `allow_origins=["*"]` with `allow_credentials=True` is rejected by browsers. You must specify exact origins when using credentials. This is the #1 CORS misconfiguration.
- **Middleware order matters** — CORS should be first (outermost) so it handles OPTIONS preflight before other middleware. Auth should be after CORS (so preflight doesn't require auth) but before your business logic. Middleware added first is called first on the request path.
- **Modifying request.body in middleware** — the request body can only be read once. If middleware reads it (e.g., for logging), the endpoint can't read it. Use `request.body()` to cache it, or avoid reading the body in middleware. For JSON logging, use `request.json()` but be aware it consumes the body.
- **Background tasks in middleware** — if you add background tasks in middleware, they may not run correctly because the middleware's response lifecycle differs from the endpoint's. Use FastAPI's `BackgroundTasks` in endpoints, not middleware.
- **Streaming responses and middleware** — middleware that reads the entire response body (e.g., for compression or modification) breaks streaming responses. Use `StreamingResponse` carefully with middleware that inspects the body.
- **Middleware doing I/O without async** — synchronous I/O in middleware blocks the event loop, just like in endpoints. Use async I/O or `asyncio.to_thread()` in middleware.
- **Forgetting to await call_next** — if you forget `await` before `call_next(request)`, you get a coroutine object instead of a response. FastAPI may handle this but the request hangs or returns 500.
- **request.state is per-request, not per-middleware** — each request gets a fresh `request.state`. Data attached in one middleware is available in subsequent middleware and the endpoint for that request, but NOT across requests. Don't use request.state for shared data.

## Practice

> [!question]- Q1. Design a middleware stack for a production FastAPI API with the following requirements: (1) CORS with specific origins, (2) request timing and logging, (3) request ID for tracing, (4) authentication via JWT, (5) rate limiting per user, (6) GZIP compression. Show the order and explain why each middleware is positioned where it is.
**Answer:**
```python
# Order (outermost → innermost):
# 1. CORS middleware (handles OPTIONS preflight, must be first)
# 2. Request ID middleware (assigns ID early for tracing)
# 3. Timing/logging middleware (measures total request time)
# 4. GZIP compression (compresses response — should be innermost)
# 5. Rate limiting middleware (checks before auth)
# 6. Auth middleware (JWT verification — short-circuits if invalid)

# app.add_middleware(CORSMiddleware, ...)  # First added = outermost
# app.add_middleware(RequestIDMiddleware)
# app.add_middleware(TimingMiddleware)
# app.add_middleware(GZipMiddleware)
# app.add_middleware(RateLimitMiddleware)
# app.add_middleware(AuthMiddleware)

# Why this order:
# CORS first: must handle OPTIONS preflight before any other middleware.
# If CORS rejects the origin, other middleware shouldn't run.
# Request ID second: assign early so all subsequent middleware and
# the endpoint can use it for logging/tracing.
# Timing third: measure from as early as possible (after CORS and ID).
# GZIP innermost: compress the final response after all modifications.
# Rate limiting before auth: don't waste auth computation on
# rate-limited requests. Also, rate limit by IP for unauthenticated
# requests and by user ID for authenticated requests.
# Auth last (before endpoint): only run auth if rate limit passed.
# Auth short-circuits with 401 if token invalid — endpoint never runs.

# Note: auth could also be a dependency (per-route) instead of middleware.
# If auth is only needed for some routes, use dependency. If all routes
# need auth, use middleware. The middleware approach is simpler for
# globally authenticated APIs.
```

> [!question]- Q2. A middleware needs to log the request body for debugging. Explain why this is problematic and design a safe alternative.
**Answer:** Problem: the request body can only be read once. If middleware reads `await request.body()` to log it, the endpoint's `await request.body()` or Pydantic model validation (which also reads the body) receives an empty body. This causes 422 validation errors or missing data. Safe alternatives: (1) **Only log for specific routes** — check `request.url.path` and only read the body for debug endpoints. For other routes, don't read the body. (2) **Cache the body after reading** — read the body once in middleware, store it in `request.state.request_body`, and let the endpoint read from there. But this requires modifying the endpoint to read from request.state instead of the normal body — defeats FastAPI's auto-parsing. (3) **Use a custom request class** — subclass `Request` that caches the body on first read. Override `body()` and `json()` to cache and return cached data. Set this as the default request class in FastAPI. (4) **Only log metadata** — log method, path, query params, headers, and content-type. Don't log the body. For debugging specific requests, enable body logging via a query param or header that triggers conditional body logging. The recommended approach: option 4 (metadata only by default, conditional body logging for debugging) combined with option 3 (custom request class that caches) if you genuinely need body logging in production.

> [!question]- Q3. Explain the difference between middleware running on the request path vs the response path. Give an example of a middleware that does something on each path.
**Answer:** The request path is everything before `call_next(request)` — the middleware receives the request, can modify it, and can short-circuit (return a response without calling the endpoint). The response path is everything after `await call_next(request)` — the middleware receives the response from the endpoint (or downstream middleware), can modify it, and must return it. Example — a timing and header-injection middleware:
```python
async def timing_and_header_middleware(request, call_next):
    # REQUEST PATH: record start time, modify request
    start = time.perf_counter()
    request.state.request_start = start
    # Can modify request here (e.g., add headers to request.state)
    
    response = await call_next(request)  # Pass to endpoint
    
    # RESPONSE PATH: modify response, measure duration
    duration = time.perf_counter() - request.state.request_start
    response.headers["X-Response-Time"] = f"{duration*1000:.1f}ms"
    response.headers["X-Custom"] = "added-by-middleware"
    return response
```
The request path sets up state and timing. The response path adds headers and logs the duration. Both paths are in the same middleware function, separated by the `call_next` await. The request path runs for every incoming request. The response path runs for every outgoing response (including error responses from the endpoint or other middleware).

> [!question]- Q4. You need to implement a middleware that blocks requests from TOR exit nodes. The check requires a network call to a TOR IP list API. Should this be middleware or a dependency? How do you handle the network call without blocking the event loop?
**Answer:** This should be middleware because: (1) it applies to ALL requests (including 404s, health checks), (2) it should short-circuit blocked requests before any routing or endpoint logic runs, (3) the check is independent of the specific route. For the network call: use an async HTTP client (aiohttp or httpx.AsyncClient) and `await` the call in the middleware. Don't use a synchronous requests library — it blocks the event loop. Cache the TOR IP list to avoid making a network call on every request — fetch once per hour (or on startup) and store in memory or Redis. The middleware checks the client IP against the cached list. This way, the network call is infrequent (cached), and when it does happen, it's async (non-blocking). For production: use a background task to periodically refresh the cache, and serve stale data if the refresh fails. The middleware itself is just a fast in-memory lookup.

> [!question]- Q5. A middleware adds a header to the response, but the header doesn't appear in the browser. The middleware code looks correct. What are the possible causes, and how do you diagnose each?
**Answer:** Possible causes: (1) **CORS header not exposed** — the header is added but the browser doesn't expose it to JavaScript because it's not in `Access-Control-Expose-Headers`. Fix: add the header name to CORS config or add `response.headers["Access-Control-Expose-Headers"] = "X-Custom-Header"`. (2) **Middleware order** — a later middleware or the framework itself overwrites the header. Check middleware order — the last middleware to modify the header wins. (3) **Error responses** — the middleware only modifies successful responses but errors are handled by exception handlers that create new responses. Use exception handlers or middleware that catches exceptions. (4) **Streaming responses** — the middleware tries to modify headers after the response has started streaming. Headers must be set before the first body chunk. (5) **Proxy stripping headers** — a reverse proxy (nginx, cloud load balancer) strips custom headers. Check proxy configuration. (6) **Browser cache** — the response is cached and the cached version doesn't have the header. Check cache-control headers. Diagnosis: use curl `-v` to see raw response headers (bypasses browser cache and CORS). Use browser DevTools → Network tab to see response headers. Check if the header appears in curl but not browser → CORS issue. Check if header appears on fresh request but not cached → cache issue. Check if header appears on some routes but not others → middleware order or exception handler issue.

## Related
[[request-response-lifecycle]]
[[dependency-injection]]
[[cors-and-security-headers]]
[[logging-and-monitoring]]
[[rate-limiting]]
[[caching]]

#status/new