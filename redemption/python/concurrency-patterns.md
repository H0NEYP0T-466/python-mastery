# Concurrency Patterns

## What it is
This is not a re-explanation of threads, processes, or async. Those are covered in [[gil-and-threading]], [[multiprocessing]], and [[async-await-and-event-loop]]. This file is a decision framework: given a workload, how do you choose between threading, multiprocessing, and async? What patterns (producer-consumer, thread pool, process pool, actor model, pipeline) solve which problems? And what are the real-world trade-offs — not textbook definitions, but the choices that determine whether your system scales or collapses under load.

## Why it matters
Knowing what a thread is doesn't tell you when to use one. In interviews and real systems, the question is never "what is the GIL" — it's "I have this problem, which concurrency model should I use and why." Getting this wrong means building a web server that uses processes for I/O (wasting memory) or a data pipeline that uses threads for CPU work (getting no speedup). This file gives you the mental model to make the right choice, the vocabulary to explain it, and the patterns to implement it.

## Core example

### The decision framework — which model when

```python
# Decision tree for choosing a concurrency model:

# Step 1: Is the workload I/O-bound or CPU-bound?
# - I/O-bound: waiting for network, disk, database, API responses
# - CPU-bound: computing, transforming, processing data with the CPU

# Step 2: If I/O-bound:
#   - How many concurrent connections? (tens? hundreds? thousands?)
#   - What's the memory budget?
#   - Do you need shared state between concurrent operations?

#   Tens to hundreds, shared state needed → Threading
#   Thousands, memory-constrained → Async
#   Thousands, shared state not needed → Async or threading

# Step 3: If CPU-bound:
#   - Is it pure Python or does it use C extensions that release the GIL?
#   - Pure Python → Multiprocessing (threads don't help due to GIL)
#   - C extensions that release GIL (NumPy, PyTorch) → Threading may help
#   - Need true parallelism → Multiprocessing

# Step 4: Hybrid workloads (most real systems):
#   - I/O + CPU: Use async for I/O, offload CPU to thread/process pool
#   - Example: FastAPI endpoint (async) → fetch DB (async) → 
#              process result (CPU, offload to thread) → return

# Quick reference:
# | Model        | Best for                    | Memory/conn | Parallelism | Complexity |
# |--------------|-----------------------------|-------------|-------------|------------|
# | Threading    | I/O-bound, shared state     | ~1MB/thread| No (GIL)    | Medium     |
# | Multiprocessing | CPU-bound pure Python   | ~10MB+/proc| Yes         | High       |
# | Async        | High-concurrency I/O        | ~KB/task    | No          | Medium-High|
# | Thread pool  | Fixed-size I/O workers      | ~1MB/thread| No          | Low        |
# | Process pool | Fixed-size CPU workers      | ~10MB+/proc| Yes         | Medium     |
```

### Producer-consumer pattern — the workhorse

```python
# The most common concurrency pattern: one or more producers generate
# work, one or more consumers process it. A queue decouples them.

# Threading version (I/O-bound):
import threading
import queue
import time

def producer(q):
    for i in range(100):
        item = produce_item(i)
        q.put(item)  # Blocks if queue is full (if maxsize set)
    q.put(None)  # Sentinel for each consumer

def consumer(q):
    while True:
        item = q.get()
        if item is None:
            break
        process_item(item)
        q.task_done()  # For q.join()

q = queue.Queue(maxsize=10)  # Bounded queue — backpressure
producers = [threading.Thread(target=producer, args=(q,)) for _ in range(2)]
consumers = [threading.Thread(target=consumer, args=(q,)) for _ in range(4)]

for t in producers + consumers:
    t.start()
for t in producers:
    t.join()
for t in consumers:
    q.put(None)  # One sentinel per consumer
    t.join()

# Key design choices:
# - Bounded queue (maxsize) provides backpressure — producers slow down
#   when consumers can't keep up. Without bounds, unbounded queue can
#   exhaust memory.
# - Sentinels (None) signal consumers to exit. One per consumer.
# - q.task_done() + q.join() lets you wait for all items to be processed.
```

### Process pool for CPU-bound work — the ML training data pipeline

```python
# For your DINOv2/GPT-2 work: data preprocessing is often CPU-bound
# (image decoding, augmentation, tokenization). Use a process pool.

from multiprocessing import Pool, cpu_count
import os

def preprocess_image(args):
    """Single image preprocessing — runs in a worker process"""
    path, target_size = args
    image = load_image(path)
    image = resize(image, target_size)
    image = augment(image)  # CPU-intensive
    return encode(image)

def preprocess_dataset(image_paths, target_size=(224, 224)):
    args = [(path, target_size) for path in image_paths]
    
    # Use cpu_count() processes — one per core
    # Each process loads its own copy of preprocessing libraries
    # (OpenCV, PIL, etc.) — memory-heavy but parallel
    with Pool(processes=cpu_count()) as pool:
        # imap_unordered: results as they complete, faster than map
        results = pool.imap_unordered(preprocess_image, args, chunksize=4)
        
        # chunksize > 1 reduces IPC overhead — each worker gets 4 items
        # at a time, processes them, returns 4 results. Better for
        # fast tasks where IPC overhead dominates.
        
        for result in results:
            save_processed(result)

# Alternative: use Pool with initializer to load heavy libraries once
def init_worker():
    global cv2, np
    import cv2, numpy as np  # Lazy import in worker

with Pool(processes=cpu_count(), initializer=init_worker) as pool:
    ...

# For your specific case:
# - Image loading from disk → I/O-bound (overlapped with compute in workers)
# - Image decoding (JPEG → array) → CPU-bound, C code (releases GIL)
# - Augmentations → depends: pure Python (needs processes), 
#   C-based (threads ok, releases GIL)
# - The process pool approach is the standard — it's what PyTorch's
#   DataLoader does with num_workers > 0.
```

### Async pipeline — the high-throughput API

```python
# For an API that handles many concurrent requests with I/O operations:
# async endpoints + async database + async HTTP client.

import asyncio
import aiohttp

async def handle_request(request_id, session, db):
    """Single request handler — fully async"""
    # 1. Fetch user (async DB)
    user = await db.fetch_user(request_id)
    if not user:
        return None
    
    # 2. Fetch related data concurrently
    orders, recommendations = await asyncio.gather(
        db.fetch_orders(user.id),
        session.get(f"https://recs.api/users/{user.id}"),
    )
    
    # 3. If CPU-intensive processing needed, offload to thread
    # processed = await asyncio.to_thread(expensive_process, orders)
    
    return {
        "user": user,
        "orders": orders,
        "recommendations": recommendations.json(),
    }

async def main():
    # Single event loop handles thousands of requests
    # Each request is a coroutine — ~KB of memory vs ~MB for a thread
    async with aiohttp.ClientSession() as session:
        db = await AsyncDatabase.connect()
        
        # Handle 1000 concurrent requests
        tasks = [
            asyncio.create_task(handle_request(i, session, db))
            for i in range(1000)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

# The architecture: async for I/O (DB, HTTP), offload CPU to threads.
# This is the FastAPI model — and it's why FastAPI can handle thousands
# of concurrent connections with a single process.
#
# Key design: bounded concurrency with a semaphore to prevent overload:
# semaphore = asyncio.Semaphore(100)  # Max 100 concurrent DB queries
# async with semaphore:
#     result = await db.query(...)
```

### Thread pool for mixed workloads — the pragmatic choice

```python
# Sometimes you have a mix of I/O and light CPU work, and you don't
# want the complexity of async or the memory overhead of processes.
# A thread pool is the pragmatic middle ground.

from concurrent.futures import ThreadPoolExecutor, as_completed
import requests

def fetch_and_process(url):
    """I/O (fetch) + light CPU (process) — fits in a thread"""
    response = requests.get(url, timeout=10)  # I/O — GIL released
    data = response.json()
    processed = process(data)  # Light CPU — holds GIL briefly
    return processed

urls = ["https://api.example.com/data/" + str(i) for i in range(100)]

# ThreadPoolExecutor manages a fixed number of threads
# Reuses threads across tasks — avoids thread creation overhead
with ThreadPoolExecutor(max_workers=10) as executor:
    # Submit all tasks
    future_to_url = {executor.submit(fetch_and_process, url): url for url in urls}
    
    # Results as they complete
    for future in as_completed(future_to_url):
        url = future_to_url[future]
        try:
            result = future.result()  # Raises if task raised
            print(f"{url}: success")
        except Exception as e:
            print(f"{url}: error — {e}")

# Why ThreadPoolExecutor over raw threads?
# - Fixed pool size — bounded resource usage
# - Reuses threads — no creation overhead per task
# - Future objects — clean result/exception handling
# - as_completed — results in completion order, not submission order
# - map — simple interface for ordered results

# When NOT to use ThreadPoolExecutor:
# - Heavy CPU-bound Python code → use ProcessPoolExecutor instead
# - Thousands of concurrent connections → use async instead
# - Tasks that hold the GIL for long periods → threads serialize
```

### Pipeline pattern — staged processing

```python
# For multi-stage data processing: stage 1 → stage 2 → stage 3
# Each stage can have different concurrency characteristics.

# Example: image processing pipeline
# Stage 1: Read images from disk (I/O-bound) → threading
# Stage 2: Decode and augment (CPU-bound) → multiprocessing
# Stage 3: Save to disk (I/O-bound) → threading

from multiprocessing import Process, Queue
import threading

def read_images(paths, output_queue):
    """Stage 1: Read images — I/O-bound, use threads"""
    for path in paths:
        image = read_image(path)  # I/O — fast with OS cache
        output_queue.put((path, image))
    output_queue.put(None)  # Sentinel

def augment_images(input_queue, output_queue):
    """Stage 2: Augment — CPU-bound, use processes"""
    while True:
        item = input_queue.get()
        if item is None:
            output_queue.put(None)  # Forward sentinel
            break
        path, image = item
        augmented = augment(image)  # CPU-intensive
        output_queue.put((path, augmented))

def save_images(input_queue):
    """Stage 3: Save — I/O-bound"""
    while True:
        item = input_queue.get()
        if item is None:
            break
        path, image = item
        save_image(path, image)

# Wire up the pipeline:
read_q = Queue()
augment_q = Queue()
save_q = Queue()

# Stage 1: threaded (multiple readers)
readers = [threading.Thread(target=read_images, args=(subset, read_q)) 
           for subset in chunk(paths, 4)]

# Stage 2: multiprocessed (CPU parallelism)
augmenters = [Process(target=augment_images, args=(read_q, augment_q)) 
              for _ in range(cpu_count())]

# Stage 3: threaded (multiple savers)
savers = [threading.Thread(target=save_images, args=(augment_q,)) 
          for _ in range(4)]

for t in readers + savers: t.start()
for p in augmenters: p.start()
for t in readers + savers + augmenters: t.join() / p.join()

# The pipeline pattern maximizes throughput by overlapping stages:
# while stage 2 is processing batch N, stage 1 is reading batch N+1,
# and stage 3 is saving batch N-1. This is the standard pattern for
# data loading in ML training — PyTorch DataLoader implements this
# with num_workers for the CPU-bound stage.
```

### Circuit breaker — preventing cascading failures

```python
# In distributed systems, when a downstream service fails, continuing
# to send requests can overload both the client and the recovering service.
# A circuit breaker prevents this by failing fast when the downstream is down.

import time
from enum import Enum

class State(Enum):
    CLOSED = 0   # Normal — requests go through
    OPEN = 1     # Failed — requests fail fast
    HALF_OPEN = 2 # Testing — allow some requests through

class CircuitBreaker:
    def __init__(self, failure_threshold=5, recovery_timeout=30):
        self.threshold = failure_threshold
        self.timeout = recovery_timeout
        self.state = State.CLOSED
        self.failure_count = 0
        self.last_failure_time = None
    
    async def execute(self, coro):
        if self.state == State.OPEN:
            if time.time() - self.last_failure_time > self.timeout:
                self.state = State.HALF_OPEN
            else:
                raise CircuitBreakerOpenError("Service unavailable")
        
        try:
            result = await coro
            self.on_success()
            return result
        except Exception as e:
            self.on_failure()
            raise
    
    def on_success(self):
        if self.state == State.HALF_OPEN:
            self.state = State.CLOSED  # Recovery confirmed
        self.failure_count = 0
    
    def on_failure(self):
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.threshold:
            self.state = State.OPEN

# Usage in an async API client:
# breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=60)
# response = await breaker.execute(session.get(url))
#
# When the downstream fails 3 times within a window, the circuit opens.
# All subsequent requests fail immediately without hitting the down service.
# After the recovery timeout, one request is allowed through (half-open).
# If it succeeds, the circuit closes. If it fails, it reopens.
#
# This is a critical pattern for microservices — it prevents a single
# failing service from bringing down the entire system.
```

### Bounded concurrency — the unsung hero

```python
# Unbounded concurrency is the #1 cause of production incidents.
# Whether using threads, processes, or async, you MUST bound concurrency.

# Async — semaphore (already shown)
semaphore = asyncio.Semaphore(100)

# Threading — bounded queue + fixed thread pool
from queue import Queue
from threading import Thread

q = Queue(maxsize=100)  # Producers block when full — backpressure
workers = [Thread(target=worker_fn, args=(q,)) for _ in range(10)]

# Multiprocessing — bounded Pool
from multiprocessing import Pool
pool = Pool(processes=8)  # Fixed size
# Use imap with chunksize for bounded, chunked processing

# Why bound?
# - Memory: unbounded queues/tasks accumulate in memory
# - Downstream protection: don't overwhelm DBs, APIs, or disk I/O
# - Fairness: prevent one user/request type from monopolizing resources
# - Stability: bounded systems degrade gracefully; unbounded systems crash

# The rule: every concurrent system needs a backpressure mechanism.
# Without it, load spikes → queue growth → memory exhaustion → OOM kill.
```

## Common mistakes / gotchas

- **Using threads for CPU-bound Python code** — due to the GIL, threads don't provide parallelism for pure Python. Use processes. But for C extensions that release the GIL (NumPy, PyTorch), threads can help.
- **Using async for CPU-bound work** — async doesn't provide parallelism. It provides concurrency for I/O. CPU work in async blocks the event loop. Offload to threads or processes.
- **Unbounded concurrency** — the most common production bug. Always use semaphores, bounded queues, or fixed-size pools. Unbounded concurrency = memory exhaustion = crash.
- **Ignoring backpressure** — if producers are faster than consumers, the queue grows. Bounded queues provide natural backpressure — producers block when full. Unbounded queues silently grow until OOM.
- **Not handling exceptions in workers** — in thread/process pools, exceptions in workers are re-raised when you retrieve the result. If you never retrieve the result, the exception is silently swallowed. Always check results.
- **Deadlock with multiple locks** — acquiring locks in different orders across threads/processes causes deadlock. Always acquire locks in a consistent global order. Use `RLock` if the same thread needs to acquire the same lock multiple times.
- **Process pool with large data** — passing large data to pool workers involves pickling, which can be slow and memory-intensive. Use shared memory, initializer for shared data, or chunk data appropriately.
- **Async code mixing sync and async** — calling async functions from sync code (or vice versa) requires careful bridging. Use `asyncio.run()` for entry points, `asyncio.to_thread()` for sync-in-async, and never block the event loop.

## Practice

> [!question]- Q2. You're building a web scraper that needs to fetch 10,000 pages, extract data, and save to a database. Each fetch takes 0.5-2s (variable), extraction takes 50ms (CPU), and DB insert takes 5ms. Design the architecture. Justify each choice.
**Answer:** Three-stage pipeline: (1) Fetching: use async with aiohttp and a semaphore (e.g., 100 concurrent) — I/O-bound, high concurrency, async is most memory-efficient. (2) Extraction: light CPU (50ms) — can be done in the same async coroutine if it's fast enough, or offload to a thread pool with `asyncio.to_thread()` if it blocks. Given 50ms is short and the GIL is released during I/O, doing it inline in the async coroutine is acceptable if the extraction is pure Python but fast. (3) Database inserts: use async DB driver (asyncpg for PostgreSQL) with a connection pool — I/O-bound, async is appropriate. The overall architecture: async fetch → (optional thread for extraction) → async DB insert, all in a single event loop with bounded concurrency via semaphore. For 10,000 pages at ~1s average fetch with 100 concurrent: ~100 seconds total. Memory: ~100 concurrent tasks × KB each = minimal. Alternative: use Scrapy (which uses async/Twisted) — same model but with built-in retry, robots.txt respect, and middleware.

> [!question]- Q3. Compare the actor model (like Erlang/Akka) with Python's concurrency approaches. Why doesn't Python have a built-in actor model, and how would you implement actor-like behavior in Python?
**Answer:** The actor model: independent actors that communicate via asynchronous message passing, no shared state, actors process one message at a time, failures are supervised. Python doesn't have a built-in actor model because Python's concurrency primitives (threads, processes, async) are lower-level — the actor model is a pattern built on top of these, not a primitive. Python's philosophy is to provide building blocks, not enforce a paradigm. You can implement actor-like behavior in Python: (1) Use `multiprocessing.Queue` for message passing between processes — each process is an actor that loops, receives messages, and processes them one at a time. (2) Use `asyncio.Queue` with async actors — each actor is an async task that processes messages from its queue. (3) Use libraries like `pykka` (Akka-inspired) or `Thespian` (actor framework). The key insight: the actor model is about message passing + isolation + supervision. Python provides the message passing (Queue) and isolation (processes), but you must implement the supervision and message-loop pattern yourself. For your ML work, an actor model would be useful for a distributed training coordinator — each worker is an actor that reports metrics to a supervisor actor.

> [!question]- Q4. A FastAPI endpoint needs to: (1) validate input, (2) query a database, (3) call an external ML model for inference, (4) save results to the database, (5) send a notification. Each step has different characteristics. Design the endpoint with the right concurrency model for each step.
**Answer:** The endpoint is async (FastAPI default). Step 1 (validation): synchronous, fast — inline. Step 2 (DB query): async with asyncpg — `await db.execute()`. Step 3 (ML inference): depends — if the model is a C extension that releases the GIL (PyTorch, TensorFlow), use `await asyncio.to_thread(model.predict(), input)` — runs in a thread pool without blocking the event loop. If it's pure Python CPU-bound, use a process pool (but the overhead may not be worth it for a single request). Step 4 (save DB): async, `await db.save()`. Step 5 (notification): fire-and-forget — use FastAPI's `BackgroundTasks` to send the notification after responding, so the client doesn't wait. The overall pattern: async for I/O (DB), thread pool for model inference (if GIL-releasing), background tasks for non-critical post-processing. This is the standard FastAPI architecture — and it handles thousands of concurrent requests because the event loop is only blocked during the actual model inference (which is in a thread), and even then, other requests can run on the event loop while the thread is computing.

> [!question]- Q5. You have a system that processes real-time stock price data: 10,000 updates/second, each update needs to be enriched with company data (cached), aggregated into 1-second windows, and stored in a time-series database. Design the architecture with appropriate concurrency patterns for each stage.
**Answer:** Four-stage pipeline: (1) Ingestion: async with a WebSocket or UDP listener — high throughput, I/O-bound, async handles 10K+ connections efficiently. Use a bounded queue (asyncio.Queue with maxlen) as a buffer between ingestion and processing — if processing can't keep up, drop oldest updates (backpressure via queue overflow). (2) Enrichment: look up company data from an in-memory cache (Redis or local dict) — this is fast, can be done inline in the async handler. If the cache misses, fetch from DB asynchronously. (3) Windowing: maintain in-memory 1-second windows per stock symbol — use a dictionary mapping symbol → list of prices in current window. Every 1 second (scheduled task), flush completed windows. This is stateful — use asyncio.Lock if multiple coroutines update the same symbol's window, or use per-symbol locks for finer granularity. (4) Storage: batch insert completed windows into the time-series DB — use async DB driver, batch multiple windows per insert for efficiency. A separate background task handles the 1-second flush: `while True: await asyncio.sleep(1); flush_windows()`. The key design: async for high-throughput I/O, in-memory state for low-latency aggregation, batched async writes for efficient storage. This architecture can handle 10K+ updates/second on a single process because the event loop efficiently handles the I/O, and the in-memory operations are fast enough to not block.

## Related
[[gil-and-threading]]
[[multiprocessing]]
[[async-await-and-event-loop]]
[[memory-management-and-gc]]
[[data-structures-and-complexity]]

#status/new