# Request-Response Lifecycle

## What it is
When an HTTP request hits a FastAPI endpoint, it traverses multiple layers: TCP connection, TLS handshake (if HTTPS), HTTP parsing, ASGI server (uvicorn), ASGI app (FastAPI), middleware stack, routing, dependency injection, request validation, endpoint execution, response serialization, response middleware, and finally the HTTP response back to the client. Each layer adds latency and potential failure points. Understanding this lifecycle is what separates "my API works" from "my API works and I know why it's slow when it isn't." This file traces the full path, identifies where time is spent, and explains the ASGI protocol that makes FastAPI async possible.

## Why it matters
In interviews, system design questions about APIs assume you understand the request lifecycle. In production, debugging latency issues requires knowing which layer is the bottleneck — is it TLS handshake time, ASGI middleware overhead, database query latency, or response serialization? For your work — building APIs that serve ML models, handling concurrent requests, optimizing inference latency — the request lifecycle is the framework within which everything else operates. You can't optimize what you don't understand.

## Core example

### The full request path — layer by layer

```
Client
  │
  │ 1. TCP connection (3-way handshake: SYN, SYN-ACK, ACK)
  │    ~1-50ms depending on network latency
  │
  │ 2. TLS handshake (if HTTPS)
  │    ~1-2 RTTs for TLS 1.3, ~2-3 for TLS 1.2
  │    Session resumption skips this (0-RTT)
  │
  │ 3. HTTP request (headers + body)
  │    Body may be streamed (chunked) or sent all at once
  │
  ▼
uvicorn (ASGI server)
  │ 4. Accept TCP connection
  │ 5. Parse HTTP request (headers, method, path, body)
  │ 6. Create ASGI scope dict (the ASGI "environment")
  │ 7. Send ASGI: http.request messages to the app
  │    (body may be sent in chunks for streaming uploads)
  │
  ▼
FastAPI (ASGI app)
  │ 8. Execute middleware stack (on_request phase)
  │    Each middleware can: modify request, short-circuit, or pass through
  │    Order: first-in, first-called (outermost middleware first)
  │
  │ 9. Routing — match path + method to endpoint
  │    FastAPI uses a trie-based router — O(path segments) lookup
  │    Path parameters are extracted during routing
  │
  │ 10. Dependency injection — resolve all Depends() for the endpoint
  │     Dependencies can be synchronous or async
  │     They're resolved in dependency order (depth-first)
  │     Each dependency can: raise HTTPException, return value, or yield (cleanup)
  │
  │ 11. Request validation — Pydantic validates request body/query/path
  │     If validation fails → HTTPException 422, response built immediately
  │     No endpoint code runs on validation failure
  │
  │ 12. Endpoint execution — your actual function runs here
  │     If async: awaited on the event loop (non-blocking)
  │     If sync: run in thread pool executor (offloads from event loop)
  │     This is where DB queries, ML inference, external API calls happen
  │
  │ 13. Response serialization — Pydantic serializes the return value
  │     If return type is Pydantic model: model_dump() → dict
  │     If return type is plain: jsonable_encoder → dict
  │     This is where serialization errors occur (non-JSON-serializable types)
  │
  │ 14. Execute middleware stack (on_response phase, in reverse order)
  │     Last-in, first-called (innermost middleware first for response)
  │     Each middleware can: modify response, log, or pass through
  │
  │ 15. Build ASGI: http.response.start + http.response.body messages
  │
  ▼
uvicorn (ASGI server)
  │ 16. Serialize ASGI messages to HTTP response
  │ 17. Write to TCP connection
  │ 18. Keep-alive: connection may be reused for next request
  │
  ▼
Client receives HTTP response
```

### ASGI — the protocol that makes async FastAPI possible

```python
# ASGI (Asynchronous Server Gateway Interface) is the async counterpart
# to WSGI (which Flask/Django use). An ASGI app is a coroutine that
# receives a scope (dict), receive (awaitable callable), and send
# (awaitable callable).

async def asgi_app(scope, receive, send):
    # scope: dict with method, path, headers, query_string, etc.
    # receive: await to get ASGI events (http.request, http.disconnect)
    # send: await to send ASGI events (http.response.start, http.response.body)
    
    # FastAPI is an ASGI app. uvicorn is an ASGI server that calls
    # FastAPI's app(scope, receive, send) for each request.
    
    # The ASGI event cycle:
    # 1. Server calls app(scope, receive, send)
    # 2. App awaits receive() to get the request body (if any)
    # 3. App processes the request
    # 4. App awaits send({"type": "http.response.start", ...})
    # 5. App awaits send({"type": "http.response.body", "body": b"..."})
    # 6. App returns — request complete
    
    # ASGI supports more than HTTP: websockets, lifespans (startup/shutdown),
    # and other protocols. This is why FastAPI supports WebSockets natively —
    # they're part of the ASGI spec.
```

### Middleware execution order — the onion model

```python
from fastapi import FastAPI
import time

app = FastAPI()

# Middleware is added in order — but executes like an onion:
# Request: A → B → C → endpoint
# Response: endpoint → C → B → A

@app.middleware("http")
async def middleware_a(request, call_next):
    print("A: before")
    start = time.time()
    response = await call_next(request)  # Passes to next middleware/endpoint
    duration = time.time() - start
    print(f"A: after ({duration:.3f}s)")
    response.headers["X-Middleware-A"] = "processed"
    return response

@app.middleware("http")
async def middleware_b(request, call_next):
    print("B: before")
    response = await call_next(request)
    print("B: after")
    response.headers["X-Middleware-B"] = "processed"
    return response

@app.get("/")
async def root():
    print("ENDPOINT")
    return {"message": "hello"}

# Request to /:
# Output:
# A: before
# B: before
# ENDPOINT
# B: after
# A: after (0.005s)

# The key insight: call_next() passes control to the next layer.
# Everything before call_next runs on the way IN (request).
# Everything after call_next runs on the way OUT (response).
# This is the same pattern as context managers and decorators.

# Middleware order matters for:
# - CORS middleware should be near the outermost (first in) so it
#   handles preflight OPTIONS requests before any other middleware
# - Authentication middleware should be before business logic but
#   after CORS (so CORS preflight doesn't require auth)
# - Logging middleware is usually outermost (logs all requests)
# - GZIP compression is usually innermost (compresses the response
#   after all other modifications)
```

### Where time is spent — profiling the lifecycle

```python
# To understand where your API spends time, instrument each layer:

import time
from fastapi import Request

@app.middleware("http")
async def timing_middleware(request: Request, call_next):
    start = time.perf_counter()
    
    # Request received → ASGI
    request_start = time.perf_counter()
    
    response = await call_next(request)
    
    # Endpoint done → response ready
    response_time = time.perf_counter() - request_start
    
    total_time = time.perf_counter() - start
    
    # Log: total time vs endpoint time
    # The difference is middleware overhead + response serialization
    logger.info(
        f"{request.method} {request.url.path} "
        f"endpoint={response_time*1000:.1f}ms "
        f"total={total_time*1000:.1f}ms "
        f"status={response.status_code}"
    )
    
    return response

# For deeper profiling within the endpoint:
@app.get("/predict/")
async def predict(input: InputModel):
    endpoint_start = time.perf_counter()
    
    # Validation time (Pydantic) — included in endpoint_start
    # but you can measure separately by timing the function entry
    
    # Inference time
    inference_start = time.perf_counter()
    result = model.predict(input.data)
    inference_time = time.perf_counter() - inference_start
    
    # Serialization time
    output = OutputModel(result=result)  # Pydantic serialization
    
    total = time.perf_counter() - endpoint_start
    
    return {
        "prediction": output,
        "metrics": {
            "inference_ms": inference_time * 1000,
            "total_ms": total * 1000,
        }
    }

# For ML serving: inference time usually dominates (90%+ of total).
# For CRUD APIs: database query time usually dominates.
# For high-concurrency APIs: event loop blocking (sync code in async
# endpoint) is the silent killer — it serializes all requests.
```

### The event loop in the request lifecycle

```python
# FastAPI runs on an asyncio event loop (via uvicorn). Each async
# endpoint is a coroutine scheduled on this loop. The key question:
# what happens when you mix async and sync code?

@app.get("/fast/")
async def fast_endpoint():
    # Pure async — yields to event loop during I/O
    data = await db.fetch()  # Yields — other requests run during DB wait
    return {"data": data}

@app.get("/slow/")
async def slow_endpoint():
    # Sync code in async endpoint — BLOCKS the event loop
    time.sleep(5)  # Blocks for 5 seconds — NO other requests can run
    # Even though this is an async function, time.sleep() is synchronous
    # and holds the GIL, preventing the event loop from scheduling
    # other coroutines.

@app.get("/fixed/")
async def fixed_endpoint():
    # Offload sync code to thread pool
    result = await asyncio.to_thread(expensive_sync_computation)
    return {"result": result}
    # The event loop is free to handle other requests while the
    # computation runs in a thread pool.

# The rule: in an async endpoint, every blocking operation must be
# either: (1) an async version (await db.fetch() instead of db.fetch()),
# or (2) offloaded to a thread/process pool (asyncio.to_thread()).
# If you call sync code directly in an async endpoint, you block the
# event loop — and since FastAPI uses a single event loop per worker,
# ALL requests are blocked, not just the one calling the sync code.
```

### Connection handling — keep-alive and timeouts

```python
# HTTP keep-alive: after a response, the TCP connection stays open
# for subsequent requests. This avoids the TCP + TLS handshake overhead
# for each request. uvicorn enables keep-alive by default.

# Timeout configuration (uvicorn):
# $ uvicorn main:app --timeout-keep-alive 5  # Close idle connections after 5s
# $ uvicorn main:app --timeout-graceful-shutdown 5  # Wait 5s for requests to finish

# In FastAPI, you can also set per-request timeouts:
import asyncio
from asyncio import TimeoutError

@app.get("/with-timeout/")
async def with_timeout():
    try:
        async with asyncio.timeout(5):  # Python 3.11+
            result = await external_api_call()
            return {"result": result}
    except TimeoutError:
        return {"error": "upstream timed out"}, 504

# For older Python:
# async with asyncio.wait_for(external_api_call(), timeout=5):
#     ...

# Connection pooling: for outbound HTTP calls (your API calling other APIs),
# use a connection pool (aiohttp ClientSession, httpx Client) to reuse
# TCP connections. Creating a new connection for each request adds
# 50-500ms of latency (DNS + TCP + TLS).

# For your ML inference API: the inbound connection (client → your API)
# benefits from keep-alive. The outbound connection (your API → model server,
# DB, or cache) benefits from connection pooling. Both reduce latency
# by avoiding repeated handshakes.
```

## Common mistakes / gotchas

- **Sync code in async endpoints** — calling `time.sleep()`, `requests.get()`, or synchronous DB drivers in an async endpoint blocks the event loop, serializing all requests. Use async alternatives or `asyncio.to_thread()`.
- **Middleware that doesn't await call_next** — if you forget `await` before `call_next(request)`, the middleware returns a coroutine object instead of a response. FastAPI handles this but the request hangs or returns 500.
- **Modifying response after it's sent** — once you `send()` the response body in ASGI, you can't modify it. In FastAPI middleware, modifications must happen before returning the response from `call_next`.
- **Long-running sync endpoints without offloading** — if your endpoint runs a 30-second ML inference synchronously, the event loop is blocked for 30 seconds. All other requests queue up. Use a background task model: accept the request, return a job ID, and let the client poll for results.
- **Not handling http.disconnect** — if a client disconnects mid-request, the ASGI server sends a `http.disconnect` event. If your endpoint doesn't check for this, it continues processing a request whose client is gone. Use `request.scope["disconnected"]` or catch `asyncio.CancelledError`.
- **Assuming request body is always available** — for large file uploads, the request body is streamed. If you try to read it multiple times without caching, the second read returns nothing. Use `await request.body()` to cache it, or `await request.stream()` for streaming.
- **Ignoring uvicorn workers** — running uvicorn with a single worker (`uvicorn main:app`) uses one CPU core. For CPU-bound workloads (ML inference), use multiple workers (`uvicorn main:app --workers 4`) or a process manager. But be careful: multiple workers mean multiple event loops, each with its own memory (model loaded 4x).

## Practice

> [!question]- Q1. A FastAPI endpoint takes 200ms in local testing but 2s in production. The endpoint makes a single database query that takes 50ms. Where is the remaining 1.75s likely spent, and how do you diagnose each?
**Answer:** The 1.75s gap is likely in: (1) Network latency between client and server — measure with `ping` and `traceroute`. If the client is far from the server, add a CDN or edge deployment. (2) TLS handshake overhead — if each request does a full TLS handshake (no session resumption), add ~100-300ms per request. Check if keep-alive is working (Connection: keep-alive header). (3) Database connection overhead — if a new DB connection is created per request (no connection pool), add ~50-200ms. Use connection pooling (asyncpg pool, SQLAlchemy pool). (4) Event loop blocking — if other requests are blocking the event loop (sync code in async endpoints), your request queues. Check with py-spy or add timing middleware. (5) DNS resolution — if your API calls external services and DNS is slow, add ~100-500ms. Use a connection pool with DNS caching. Diagnosis: add timing middleware that breaks down request time into middleware, endpoint, and response serialization. Use database query logging for DB time. Use distributed tracing (OpenTelemetry) for end-to-end latency across services.

> [!question]- Q2. Explain the difference between an ASGI server, an ASGI app, and ASGI middleware. Give an example of each and how they interact in the request lifecycle.
**Answer:** ASGI server (uvicorn, hypercorn, daphne): handles TCP/TLS connections, parses HTTP requests, creates ASGI scope, calls the ASGI app, and sends the HTTP response. It's the network layer. ASGI app (FastAPI, Starlette, Quart): receives scope/receive/send, processes the request, and sends the response via ASGI events. It's the application logic layer. ASGI middleware (fastapi.middleware, custom middleware): sits between the server and app, can inspect/modify requests and responses, short-circuit requests, or add side effects (logging, auth, CORS). It's the cross-cutting concern layer. Interaction: client → TCP → uvicorn (server, parses HTTP → ASGI events) → middleware stack (on_request) → FastAPI app (routing, validation, endpoint) → middleware stack (on_response) → uvicorn (ASGI events → HTTP response) → TCP → client. The server handles the network, the app handles the logic, the middleware handles cross-cutting concerns. Each layer only knows about its immediate neighbors — the server doesn't know about FastAPI, FastAPI doesn't know about uvicorn, they communicate only through the ASGI interface.

> [!question]- Q3. You have a FastAPI endpoint that needs to call an external API (1s latency) and run a CPU-heavy ML inference (500ms). Both operations are independent. Design the endpoint to minimize total latency. What's the theoretical minimum?
**Answer:** If the operations are independent, run them concurrently:
```python
@app.get("/predict/")
async def predict(input: InputModel):
    # Run external API call and ML inference concurrently
    api_task = asyncio.create_task(external_api_call(input))
    # ML inference is sync — offload to thread
    inference_task = asyncio.to_thread(model.predict, input.data)
    
    # Wait for both
    api_result, inference_result = await asyncio.gather(api_task, inference_task)
    
    return combine(api_result, inference_result)
```
Total latency = max(1s, 500ms) = 1s (the slower of the two). The theoretical minimum is 1s — you can't make the external API faster, and the inference runs in parallel. If you ran them sequentially, total = 1.5s. The concurrent approach saves 500ms (33% improvement). Key insight: when operations are independent, run them in parallel. The total time is the maximum of the individual times, not the sum. This is a standard optimization in API design — fan-out to multiple backends, gather results.

> [!question]- Q4. A client uploads a 1GB file to a FastAPI endpoint. The endpoint needs to process the file and return a result. Describe the memory and latency implications of different approaches.
**Answer:** Approach 1: `await request.body()` — reads the entire file into memory (1GB RAM). Simple but memory-intensive. If 10 clients upload simultaneously, 10GB RAM. Approach 2: `await request.stream()` — streams the file in chunks. Memory: chunk size (e.g., 1MB) regardless of file size. But you must process incrementally — can't seek or re-read. Approach 3: save to disk first — `with open(tmp, "wb") as f: async for chunk in request.stream(): f.write(chunk)`. Memory: minimal. Latency: disk write overhead, but you can process after the full file is saved. Approach 4: streaming processing — process each chunk as it arrives (e.g., compute hash, validate format). Memory: minimal. Latency: processing overlaps with upload. For a 1GB file: approach 1 is dangerous (OOM risk), approach 2-4 are safe. The choice depends on whether you need the full file (save to disk) or can process incrementally (streaming). For ML inference on large files: save to disk first, then process, because most ML models need the full input. For validation or hashing: streaming is best.

> [!question]- Q5. Explain why FastAPI runs sync endpoints in a thread pool executor, and what the implications are for performance and concurrency.
**Answer:** FastAPI runs sync endpoints in a thread pool executor (via `run_in_threadpool`) because the event loop can't block — if a sync endpoint ran directly on the event loop, it would block all other requests. The thread pool executor offloads sync code to a separate thread, freeing the event loop to handle other requests. Implications: (1) Sync endpoints don't block the event loop — they block a thread from the pool. The default pool size is based on CPU count (typically 40 threads). (2) If you have many concurrent sync endpoints, they consume threads from the pool. If all threads are busy, new requests queue. (3) Thread pool overhead: context switching between threads, GIL contention (Python threads share the GIL, so CPU-bound sync code doesn't get parallelism). (4) For I/O-bound sync code (like `requests.get()`), the GIL is released during I/O, so threads can run concurrently — but you're still using thread pool slots that could be used by async endpoints. (5) Best practice: use async endpoints with async I/O (no thread pool needed, scales to thousands of concurrent requests). Use sync endpoints only when the code is genuinely synchronous and fast, or when you have no async alternative. For CPU-bound sync code, use multiprocessing or offload to a separate service.

## Related
[[async-await-and-event-loop]]
[[middleware]]
[[dependency-injection]]
[[error-handling-and-exception-handlers]]
[[async-endpoints-when-to-use]]
[[streaming-responses]]

#status/new