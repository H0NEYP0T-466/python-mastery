# Async Endpoints — When to Use

## What it is
In FastAPI, an endpoint defined with `async def` runs on the event loop and can `await` I/O operations without blocking other requests. A `sync def` endpoint runs in a thread pool executor. This file does NOT re-explain how async/async works — that's covered in [[async-await-and-event-loop]]. This file answers the practical question: when should you make an endpoint async, when is sync fine, and what happens if you mix them wrong?

## Why it matters
This is one of the most common FastAPI interview questions and production mistakes. Using `async def` with blocking code (like `time.sleep()` or `requests.get()`) silently serializes all requests. Using `sync def` for I/O-bound endpoints wastes the thread pool and limits concurrency. Getting this right directly impacts your API's throughput and latency under load.

## Core example

### The decision framework

```python
from fastapi import FastAPI
import time, asyncio
import requests  # sync HTTP client
import httpx     # async HTTP client

app = FastAPI()

# ✅ GOOD: async endpoint with async I/O
@app.get("/users/{user_id}")
async def get_user(user_id: int):
    # Async DB query — yields to event loop during wait
    user = await db.fetch_user(user_id)
    # Async HTTP call — yields during network wait
    profile = await httpx.get(f"https://api/profiles/{user_id}")
    return {"user": user.json(), "profile": profile.json()}
    # While waiting for DB or HTTP, the event loop handles
    # other requests. No threads blocked.

# ❌ BAD: async endpoint with sync I/O (BLOCKS the event loop)
@app.get("/users/{user_id}")
async def get_user_bad(user_id: int):
    user = db.fetch_user_sync(user_id)  # BLOCKS! No other requests
    profile = requests.get(f"https://api/profiles/{user_id}")  # BLOCKS!
    return {"user": user, "profile": profile.json()}
    # Even though this is async def, the sync calls hold the GIL
    # and prevent the event loop from scheduling other coroutines.
    # ALL requests queue up behind this one.

# ✅ GOOD: sync endpoint for fast, non-I/O work
@app.get("/health")
def health():
    # Quick in-memory check — no I/O, no need for async
    return {"status": "ok"}
    # Runs in thread pool, but it's so fast it doesn't matter.

# ✅ GOOD: sync endpoint with sync I/O (offloaded to thread pool)
@app.get("/report/{report_id}")
def get_report(report_id: int):
    # Sync DB driver — runs in thread pool
    # This is fine for low-concurrency endpoints
    report = db.get_report(report_id)
    return report
    # Each request uses one thread from the pool.
    # With default ~40 threads, you can handle ~40 concurrent
    # sync I/O requests. Beyond that, requests queue.
```

### The concurrency comparison

```python
import asyncio
import time
from fastapi import FastAPI

app = FastAPI()

# Simulate a slow I/O operation (100ms)
async def async_io():
    await asyncio.sleep(0.1)

def sync_io():
    time.sleep(0.1)

# 100 concurrent requests — async endpoint:
# Total time ≈ 100ms (all run concurrently on event loop)
# 0 threads blocked

# 100 concurrent requests — sync endpoint with sync I/O:
# Total time ≈ 100ms × (100 / 40 threads) ≈ 250ms
# 40 threads blocked during the wait
# If you have 1000 concurrent requests, threads exhaust and requests queue

# The difference is negligible for low traffic (< 10 concurrent requests).
# At scale, async endpoints with async I/O handle 10-100x more
# concurrent connections with the same hardware.
```

### Converting sync to async — the right way

```python
# If you have sync I/O code but want to use an async endpoint,
# you MUST offload it to a thread pool.

import asyncio
from fastapi import FastAPI

app = FastAPI()

# Option 1: asyncio.to_thread (Python 3.9+)
@app.get("/sync-call/")
async def sync_call():
    result = await asyncio.to_thread(expensive_sync_function)
    return {"result": result}
    # Runs in the default thread pool executor.
    # The event loop is free during the execution.

# Option 2: run_in_threadpool (Starlette/FastAPI built-in)
from starlette.concurrency import run_in_threadpool

@app.get("/sync-call-2/")
async def sync_call_2():
    result = await run_in_threadpool(expensive_sync_function)
    return {"result": result}
    # Same as asyncio.to_thread but uses FastAPI's thread pool.

# Option 3: Use a thread pool executor directly
from concurrent.futures import ThreadPoolExecutor

executor = ThreadPoolExecutor(max_workers=4)

@app.get("/sync-call-3/")
async def sync_call_3():
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(executor, expensive_sync_function)
    return {"result": result}
    # Use this when you need a dedicated thread pool separate
    # from FastAPI's default (e.g., for CPU-bound work).

# The key rule: if your async endpoint calls sync I/O, wrap it in
# asyncio.to_thread() or run_in_threadpool(). Never call it directly.
```

### When sync is actually better

```python
# Not every endpoint needs to be async. Here are cases where sync is fine:

# 1. Simple CRUD with a sync ORM (SQLAlchemy sync mode)
#    For low-to-medium traffic, sync is simpler and just as fast.
#    The thread pool handles concurrency adequately.

@app.post("/items/")
def create_item(item: Item):
    db.add(item)  # Sync SQLAlchemy
    db.commit()
    return item
    # If you have < 100 concurrent requests, this is fine.
    # The overhead of async + async DB driver isn't worth it.

# 2. CPU-bound endpoints (offloaded anyway)
@app.post("/compute/")
def compute_heavy(data: Data):
    result = heavy_computation(data)  # CPU-bound
    return result
    # Whether sync or async, this blocks something.
    # Sync blocks a thread. Async with to_thread also blocks a thread.
    # For true parallelism, use multiprocessing or a separate service.
    # The endpoint being async doesn't help — the GIL is the bottleneck.

# 3. Wrapping a sync library that has no async alternative
#    If you call a sync ML inference library, you're offloading to
#    thread pool regardless. The endpoint being async adds no value.
#    Use sync endpoint for simplicity.

# The rule of thumb:
# - High concurrency (100+ concurrent requests) + I/O → async endpoint + async I/O
# - Low concurrency + I/O → sync endpoint is fine
# - CPU-bound → offload to process/external service either way
# - Wrapping sync library → sync endpoint, or async with to_thread
```

### The mixed concurrency problem

```python
# What happens when you mix async and sync endpoints in the same app?

@app.get("/fast")
async def fast():
    await asyncio.sleep(0.01)  # Non-blocking
    return {"fast": True}

@app.get("/slow")
async def slow():
    await asyncio.sleep(1)  # Non-blocking but long
    return {"slow": True}

@app.get("/blocking")
async def blocking():
    time.sleep(1)  # BLOCKS the event loop
    return {"blocking": True}

# If a request hits /blocking, the event loop is blocked for 1 second.
# During that second, /fast and /slow requests CANNOT progress —
# they're queued even though they're async. The async endpoints
# are only as fast as the least-blocking endpoint on the same loop.

# Solution: run blocking endpoints on a separate thread pool.
@app.get("/blocking-fixed")
async def blocking_fixed():
    result = await asyncio.to_thread(time.sleep, 1)
    return {"blocking": True}
    # Now the event loop is free — /fast and /slow run concurrently.
```

## Common mistakes / gotchas

- **Calling sync I/O directly in async endpoints** — `requests.get()`, `time.sleep()`, sync DB drivers block the event loop. This silently serializes all requests. Always use `asyncio.to_thread()` or async alternatives.
- **Assuming async = faster** — async doesn't make a single request faster. It makes the server handle MORE concurrent requests. A single async request with one DB call takes the same time as a sync one. The benefit is concurrency, not per-request latency.
- **Using async endpoints for everything "just in case"** — if your code has no async I/O, making the endpoint async adds overhead (event loop scheduling) with no benefit. Use sync for simple, fast endpoints.
- **Mixing sync and async DB drivers in the same app** — if some endpoints use async DB (asyncpg) and others use sync DB (psycopg2 sync), the sync ones block threads. Be consistent within a service, or isolate sync endpoints to a separate worker process.
- **Forgetting that `asyncio.to_thread()` uses the default thread pool** — if you offload many long-running sync tasks, you can exhaust the thread pool and block other sync operations. Use a dedicated executor for long-running tasks.
- **Async endpoints that never yield** — an async function with no `await` is just a sync function with extra overhead. FastAPI warns about this. If there's nothing to await, make it a sync endpoint.

## Practice

> [!question]- Q1. Your FastAPI API has 3 endpoints: (1) `/predict` runs ML inference (2s, CPU-bound, sync library), (2) `/search` queries an external API (500ms, async available), `/status` returns a static health check. Design which should be async/sync and why.
**Answer:** `/predict` → sync endpoint (or async with `asyncio.to_thread()`). Since the ML inference is CPU-bound and sync, it blocks regardless. Making the endpoint async doesn't help unless you offload with to_thread. For production, run inference in a separate service and call it asynchronously. `/search` → async endpoint with async HTTP client (httpx). This is the classic I/O-bound case where async shines — while waiting for the external API, the event loop handles other requests. `/status` → sync endpoint. It's a trivial in-memory operation — no I/O, no benefit from async. The simplest and most efficient choice. Key principle: match the endpoint style to the dominant operation. Async for I/O-bound with async libraries, sync for trivial or CPU-bound operations.

> [!question]- Q2. An async endpoint calls a sync database driver directly (no to_thread). Under load, the API becomes unresponsive for ALL endpoints, including purely async ones. Explain why and fix.
**Answer:** The sync DB call blocks the event loop — it holds the GIL while waiting for the database response. Since FastAPI uses a single event loop per worker, ALL requests (even async ones) are blocked waiting for the GIL. The event loop can't schedule any other coroutines during the I/O wait. This is why a single blocking call in one endpoint freezes the entire API. Fix: wrap the sync DB call in `asyncio.to_thread()` or switch to an async DB driver (asyncpg for PostgreSQL, aiomysql for MySQL). With to_thread, the sync call runs in a thread pool and the event loop is free. With an async driver, the call yields to the event loop during I/O. For production: async drivers are preferred (no thread pool overhead), but to_thread is a valid migration path.

> [!question]- Q3. You have a FastAPI app with 50 endpoints. 45 are simple CRUD (sync ORM), 5 are high-concurrency notification endpoints (need to call external APIs). Should you make the whole app async? Explain the trade-offs.
**Answer:** No. Make only the 5 notification endpoints async. The 45 CRUD endpoints with sync ORM are fine as sync — if your concurrency is moderate (< 50 concurrent requests), the thread pool handles them adequately. Making all 50 async would require rewriting all 45 CRUD endpoints to use async ORM (SQLAlchemy async mode or TortoiseORM), which is a significant migration with risk. The trade-off: keeping CRUD as sync is simpler and lower-risk. The 5 async endpoints handle the high-concurrency case without affecting the rest. If you later need higher concurrency for CRUD, migrate gradually. The hybrid approach is common in production — most FastAPI apps have a mix. The key is isolating the async endpoints so they're not blocked by sync code (which they won't be, as long as the sync endpoints don't have blocking calls in async functions).

> [!question]- Q4. Explain why `async def` with no `await` is worse than just `def` for an endpoint.
**Answer:** An `async def` with no `await` is compiled as a coroutine, which FastAPI must schedule on the event loop. This adds overhead: the coroutine must be created, scheduled, and the event loop must context-switch to it. A `def` endpoint runs directly in the thread pool with no event loop scheduling overhead. For a trivial endpoint (like health check or simple computation), the sync version is measurably faster per request. Additionally, FastAPI emits a warning for async endpoints with no await, suggesting you make them sync. The performance difference is small (~0.1-0.5ms per request) but at scale it adds up. The rule: if there's nothing to await, don't use async def.

> [!question]- Q5. You need to call 3 independent external APIs (each takes 200ms) in one endpoint. Compare sequential vs concurrent approaches and compute the total latency for each with 100 concurrent clients.
**Answer:** Sequential (sync calls in async endpoint without to_thread, or sync endpoint):
```python
# DON'T do this in async endpoint — blocks event loop
r1 = requests.get(url1)  # 200ms
r2 = requests.get(url2)  # 200ms  
r3 = requests.get(url3)  # 200ms
# Total per request = 600ms
# With 100 concurrent clients and 40 threads: 
# 100 requests × 600ms / 40 threads ≈ 1500ms average
# Event loop blocked during each call — terrible concurrency
```

Concurrent (async with asyncio.gather):
```python
# DO this — all three run concurrently
r1, r2, r3 = await asyncio.gather(
    httpx.get(url1), httpx.get(url2), httpx.get(url3)
)
# Total per request = 200ms (the slowest of the three)
# With 100 concurrent clients on event loop:
# All 100 requests run concurrently — total ≈ 200ms + overhead
# Event loop is free during I/O — handles all 100 simultaneously
```
The concurrent approach is 3x faster per request (200ms vs 600ms) and handles 100x more concurrent clients with the same hardware. This is the canonical example of why async matters: when you have multiple independent I/O operations, run them concurrently with `asyncio.gather()`. The total latency is the maximum of the individual latencies, not the sum.

## Related
[[async-await-and-event-loop]]
[[request-response-lifecycle]]
[[concurrency-patterns]]
[[background-tasks]]
[[inference-serving-patterns]]

#status/new