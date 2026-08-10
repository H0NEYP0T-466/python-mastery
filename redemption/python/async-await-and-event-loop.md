# Async/Await and Event Loop

## What it is
Python's `async`/`await` syntax (introduced in Python 3.5 via PEP 492) provides cooperative multitasking — a single thread can run many concurrent tasks, each yielding control voluntarily when it awaits an I/O operation. Under the hood, an event loop schedules coroutines, manages their execution, and wakes them when their awaited operation completes. This is not threading — there's no preemption, no GIL contention between tasks, and no parallelism. But for I/O-bound workloads with high concurrency (thousands of connections), async is far more efficient than threads because it avoids the memory and context-switching overhead of thread stacks.

## Why it matters
Async is the foundation of FastAPI, aiohttp, asyncpg, and most modern Python web frameworks. Understanding how the event loop works — what blocks it, what doesn't, how `await` suspends and resumes — is the difference between writing FastAPI endpoints that scale and writing ones that silently degrade under load. In interviews, async questions test whether you understand the difference between concurrency and parallelism, what "blocking the event loop" means, and when async is the right tool. For your work — API serving, model inference pipelines — async is the concurrency model you'll use most often. Getting it wrong means your API appears fast in benchmarks but hangs under real load.

## Core example

### Coroutines vs regular functions — the fundamental difference

```python
import asyncio

# A regular function — runs to completion, blocks the caller
def sync_func():
    print("sync start")
    time.sleep(1)  # Blocks the entire thread for 1 second
    print("sync end")
    return 42

# An async function (coroutine) — returns a coroutine object when called,
# doesn't run until awaited or scheduled on the event loop
async def async_func():
    print("async start")
    await asyncio.sleep(1)  # Yields control to the event loop for 1s
    print("async end")
    return 42

# Calling an async function doesn't execute the body:
coro = async_func()  # Nothing printed — just creates a coroutine object

# To run it, you need an event loop:
# asyncio.run(async_func())  # Python 3.7+ — creates a loop, runs, closes

# The key difference: 'await' is a yield point. When you 'await',
# the coroutine suspends, the event loop runs other coroutines,
# and this coroutine resumes when the awaited operation completes.
# Without 'await', an async function runs just like a synchronous
# function — it doesn't yield control.
```

### The event loop — how scheduling works

```python
import asyncio

# The event loop is a single-threaded scheduler. It maintains a queue
# of tasks (coroutines that are ready to run) and runs them one at a time.
# When a coroutine hits 'await', it yields control back to the loop,
# which picks the next ready task.

async def task(name, delay):
    print(f"Task {name} starting, will sleep for {delay}s")
    await asyncio.sleep(delay)  # Yields control — other tasks run
    print(f"Task {name} waking up after {delay}s")
    return name

async def main():
    # Create three tasks — they all start immediately
    # But they don't run concurrently — they run interleaved
    t1 = asyncio.create_task(task("A", 2))
    t2 = asyncio.create_task(task("B", 1))
    t3 = asyncio.create_task(task("C", 3))
    
    # All three tasks are scheduled. The event loop runs them:
    # Task A starts → sleeps 2 → yields
    # Task B starts → sleeps 1 → yields  
    # Task C starts → sleeps 3 → yields
    # After 1s: Task B wakes → completes
    # After 2s: Task A wakes → completes
    # After 3s: Task C wakes → completes
    
    # Total time: ~3 seconds (not 6 seconds = 2+1+3)
    # Because sleeps overlap — they're concurrent, not parallel
    
    results = await asyncio.gather(t1, t2, t3)
    print(f"Results: {results}")

# asyncio.run(main())
# Output:
# Task A starting, will sleep for 2s
# Task B starting, will sleep for 1s
# Task C starting, will sleep for 3s
# Task B waking up after 1s
# Task A waking up after 2s
# Task C waking up after 3s
# Results: ['A', 'B', 'C']

# The critical insight: all three tasks run in the SAME thread.
# They're concurrent (overlapping in time) but not parallel (not
# running simultaneously on different cores). This is fine for I/O-bound
# work because I/O doesn't need the CPU — while one task waits for
# network, another can use the CPU.
```

### What blocks the event loop — the cardinal sin

```python
import asyncio
import time

async def blocking_task():
    print("Blocking task start")
    time.sleep(3)  # BAD — synchronous sleep blocks the ENTIRE event loop
    print("Blocking task end")

async def nonblocking_task():
    print("Non-blocking task start")
    await asyncio.sleep(1)  # GOOD — yields control
    print("Non-blocking task end")

async def main():
    # Both tasks start, but the blocking task holds the event loop
    t1 = asyncio.create_task(blocking_task())
    t2 = asyncio.create_task(nonblocking_task())
    
    await asyncio.gather(t1, t2)
    # Output:
    # Blocking task start
    # (3 seconds pass — nonblocking_task can't start because loop is blocked)
    # Blocking task end
    # Non-blocking task start
    # (1 second passes)
    # Non-blocking task end
    # Total: ~4 seconds
    
    # If the blocking task used await asyncio.sleep(3):
    # Both tasks would interleave, total ~3 seconds

# The rule: NEVER call blocking synchronous code inside an async function.
# This includes: time.sleep(), requests.get(), file I/O (open().read()),
# database calls with synchronous drivers, and any CPU-bound computation
# that takes significant time.

# If you MUST call blocking code:
# 1. Use asyncio.to_thread() (Python 3.9+) — runs in a thread pool
#    result = await asyncio.to_thread(blocking_function, arg)
# 2. Use loop.run_in_executor() — more control over thread/process pool
#    result = await asyncio.get_event_loop().run_in_executor(None, blocking_fn)
# 3. Use an async alternative: aiohttp instead of requests, asyncpg instead of
#    psycopg2, aiofiles instead of standard file I/O
```

### `asyncio.gather`, `wait`, and `TaskGroup` — running multiple coroutines

```python
import asyncio

async def fetch(url, delay):
    print(f"Fetching {url}")
    await asyncio.sleep(delay)
    return f"response from {url}"

async def main():
    # gather — run all coroutines concurrently, wait for all, return results
    results = await asyncio.gather(
        fetch("api/users", 2),
        fetch("api/posts", 1),
        fetch("api/comments", 3),
    )
    print(results)  # All results after ~3 seconds (max delay)
    
    # If one task raises, gather propagates the exception by default.
    # return_exceptions=True catches exceptions and returns them as results:
    results = await asyncio.gather(
        fetch("ok", 1),
        fetch("fail", 2),  # Raises
        return_exceptions=True,
    )
    # results = ["ok response", Exception(...)]
    
    # wait — returns when a condition is met (ALL or FIRST)
    # Doesn't return results — you get done/pending sets
    done, pending = await asyncio.wait(
        [fetch("a", 1), fetch("b", 2), fetch("c", 3)],
        return_when=asyncio.FIRST_COMPLETED,
    )
    # done = {task for "a"}, pending = {tasks for "b", "c"}
    # You must handle pending tasks (cancel or await them)
    
    # TaskGroup (Python 3.11+) — structured concurrency
    # async with asyncio.TaskGroup() as tg:
    #     t1 = tg.create_task(fetch("a", 1))
    #     t2 = tg.create_task(fetch("b", 2))
    # # Automatically waits for all tasks on exit
    # # If one task raises, all others are cancelled — no orphaned tasks

# gather is the most common pattern — run multiple async operations
# concurrently and collect all results. Use it when all operations
# are independent and you need all results.
```

### Semaphores — limiting concurrency

```python
import asyncio

# Without limiting: 1000 concurrent connections → server overload
async def fetch_unlimited(session, url, semaphore):
    async with semaphore:  # Limits concurrent executions
        return await session.get(url)

async def main():
    semaphore = asyncio.Semaphore(10)  # Max 10 concurrent
    
    async with aiohttp.ClientSession() as session:
        tasks = [
            asyncio.create_task(fetch_unlimited(session, url, semaphore))
            for url in urls
        ]
        results = await asyncio.gather(*tasks)
    
    # Without the semaphore, all 1000 tasks would start simultaneously.
    # With the semaphore, only 10 run at a time — as one completes,
    # another starts. This prevents overwhelming the server or hitting
    # rate limits.

# Common use cases:
# - Limit concurrent API calls to avoid rate limiting
# - Limit database connections to avoid pool exhaustion
# - Limit concurrent file operations to avoid I/O saturation
# - Limit memory usage by bounding concurrent in-flight operations
```

### Async context managers — `async with`

```python
import asyncio

# Some resources need async setup/teardown — like database connections,
# HTTP sessions, or file locks.

class AsyncDatabase:
    async def connect(self):
        print("Connecting to database...")
        await asyncio.sleep(1)
        self.connected = True
    
    async def close(self):
        print("Closing database connection...")
        await asyncio.sleep(0.5)
        self.connected = False
    
    async def __aenter__(self):
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
        # Return False to propagate exceptions, True to suppress

# Usage:
# async with AsyncDatabase() as db:
#     await db.query("SELECT ...")
# # Automatically closes on exit, even if an exception occurs

# Many async libraries provide async context managers:
# async with aiohttp.ClientSession() as session:
#     async with session.get(url) as response:
#         data = await response.text()
#
# async with asyncio.Lock():
#     # Critical section
#
# The pattern is identical to synchronous context managers but uses
# __aenter__/__aexit__ which are awaited.
```

### Async locks — synchronization in a single thread

```python
import asyncio

# Why do you need a lock in a single-threaded async program?
# Because while the event loop is single-threaded, coroutines can
# be suspended and resumed at await points. If two coroutines access
# shared state, they can interleave at await points, causing race conditions.

counter = 0
lock = asyncio.Lock()

async def increment_bad():
    global counter
    for _ in range(1000):
        # This is NOT atomic — the read-modify-write can interleave
        # at the 'await asyncio.sleep(0)' yield point
        current = counter
        await asyncio.sleep(0)  # Yield point — another coroutine can run
        counter = current + 1

async def increment_good():
    global counter
    for _ in range(1000):
        async with lock:  # Only one coroutine can hold the lock
            current = counter
            await asyncio.sleep(0)  # Still yields, but lock prevents others
            counter = current + 1

async def main():
    counter = 0
    await asyncio.gather(
        increment_bad(),  # Result: < 2000 (race condition)
        increment_bad(),
    )
    print(f"Bad: {counter}")  # Likely < 2000
    
    counter = 0
    await asyncio.gather(
        increment_good(),  # Result: exactly 2000
        increment_good(),
    )
    print(f"Good: {counter}")  # Exactly 2000

# The lock in async doesn't prevent preemption — it prevents other
# coroutines from entering the critical section. The event loop still
# runs other coroutines, but they block on 'async with lock' until
# the lock is released. This is necessary for correctness when shared
# state is modified across await points.
```

### Running CPU-bound work in async — the right way

```python
import asyncio

# Async is for I/O-bound work. CPU-bound work blocks the event loop.
# But sometimes you need to run CPU-bound code from an async context.

async def process_with_cpu(data):
    # WRONG — blocks the event loop
    # result = heavy_computation(data)
    
    # RIGHT — run in a thread pool
    result = await asyncio.to_thread(heavy_computation, data)
    
    # Or with a process pool for true parallelism:
    # loop = asyncio.get_event_loop()
    # result = await loop.run_in_executor(process_pool, heavy_computation, data)
    
    return result

# asyncio.to_thread (Python 3.9+) is the simplest — it runs the function
# in the default thread pool executor and awaits the result. The function
# runs in a separate thread, so it doesn't block the event loop.
# But due to the GIL, Python CPU-bound code in a thread doesn't get
# parallelism — it just avoids blocking the event loop.
#
# For true parallelism with CPU-bound Python code, use a ProcessPoolExecutor:
# process_pool = concurrent.futures.ProcessPoolExecutor()
# result = await loop.run_in_executor(process_pool, heavy_computation, data)
#
# This runs in a separate process (bypassing the GIL) but has pickling
# overhead for the input and output data.
```

## Common mistakes / gotchas

- **Blocking the event loop** — calling synchronous blocking code (`time.sleep()`, `requests.get()`, synchronous file I/O) inside an async function blocks ALL coroutines. Use `await asyncio.sleep()`, `aiohttp`, `aiofiles`, or `asyncio.to_thread()`.
- **Forgetting `await`** — calling an async function without `await` just creates a coroutine object. The function never runs. This is a silent bug — no error, just nothing happens. Linters (flake8 with flake8-async) catch this.
- **Creating tasks but not awaiting them** — `asyncio.create_task()` schedules a task, but if you don't `await` it or `gather` it, the program may exit before the task completes. In Python 3.8+, unawaited tasks generate warnings.
- **Async locks for CPU-bound synchronization** — async locks only work within a single event loop. They don't protect against multiprocessing or threading. For cross-process/thread synchronization, use `multiprocessing.Lock` or `threading.Lock`.
- **Exception handling in fire-and-forget tasks** — if you `create_task` and don't `await` it, exceptions in the task are not raised in the caller. They're logged but not propagated. Always gather or wrap tasks with exception handlers.
- **Async generators** — `async def` with `yield` creates an async generator. You iterate with `async for`. They're useful for streaming data (e.g., streaming API responses) but require careful cleanup.
- **Canceling tasks** — `task.cancel()` requests cancellation. The task must handle `asyncio.CancelledError` to clean up properly. If the task ignores it (e.g., in a `try/except Exception` that catches `CancelledError`), the task won't cancel. In Python 3.8+, `CancelledError` inherits from `BaseException`, not `Exception`, so `except Exception` doesn't catch it — but `except:` does.
- **Running async in threads** — you can't share an event loop across threads. Each thread needs its own loop. Use `asyncio.new_event_loop()` in the thread. For cross-thread async calls, use `asyncio.run_coroutine_threadsafe()`.

## Practice

> [!question]- Q1. You have an API endpoint that needs to fetch data from 3 external services (user profile, order history, recommendations) and combine them. Each fetch takes ~200ms. Compare synchronous, threading (3 threads), and async approaches in terms of latency and resource usage.
**Answer:** Synchronous: ~600ms total (200ms × 3 sequential). Threading with 3 threads: ~200ms total (all fetch concurrently) but with thread overhead (~1MB per thread stack, context switching). Async with 3 tasks: ~200ms total (all fetch concurrently) with minimal overhead (~no additional memory per task, no context switching). The async approach is the most efficient — same latency as threading but with far less memory and no thread management overhead. For a web server handling 1000 concurrent requests, the threading approach would need 3000 threads (3GB+ memory) while async needs 1000 tasks in a single thread (~MBs of memory). This is why FastAPI and other async frameworks scale better for I/O-bound APIs.

> [!question]- Q2. Explain why this code doesn't work as expected and fix it:
```python
async def fetch_all(urls):
    results = []
    for url in urls:
        result = await fetch(url)
        results.append(result)
    return results
```
**Answer:** This fetches URLs sequentially — each `await fetch(url)` completes before the next starts. Total time = sum of all fetch times. The fix: use `asyncio.gather` to fetch concurrently:
```python
async def fetch_all(urls):
    tasks = [asyncio.create_task(fetch(url)) for url in urls]
    results = await asyncio.gather(*tasks)
    return results
```
Or more concisely:
```python
async def fetch_all(urls):
    return await asyncio.gather(*(fetch(url) for url in urls))
```
This creates all tasks first, then awaits them all concurrently. Total time = max of all fetch times (assuming no server-side rate limiting). The key insight: `await` suspends the coroutine but doesn't start other coroutines — you must explicitly create tasks or use `gather` to run things concurrently.

> [!question]- Q3. What happens when you call `asyncio.sleep(0)`? Why would you ever do this?
**Answer:** `asyncio.sleep(0)` yields control to the event loop without waiting — it's a way to explicitly yield so other pending coroutines can run. Use cases: (1) In a long-running computation within an async function, periodically call `sleep(0)` to let other tasks make progress. (2) In producer-consumer patterns, yield after producing to let consumers process. (3) In cooperative scheduling, allow the event loop to process pending callbacks. It's a "cooperative yield" — similar to `threading.yield()` but for async. In practice, you rarely need this because I/O operations (`await` on network calls, etc.) already yield. But for CPU-heavy async code (which you should avoid), `sleep(0)` prevents starvation of other tasks.

> [!question]- Q4. Design a rate-limited async HTTP client that makes at most 10 requests per second to a single domain. Use a token bucket algorithm.
**Answer:**
```python
import asyncio
import time

class RateLimiter:
    def __init__(self, rate_per_second):
        self.rate = rate_per_second
        self.tokens = rate_per_second  # Start with full bucket
        self.last_refill = time.monotonic()
        self.lock = asyncio.Lock()
    
    async def acquire(self):
        async with self.lock:
            now = time.monotonic()
            # Refill tokens based on elapsed time
            elapsed = now - self.last_refill
            self.tokens += elapsed * self.rate
            self.tokens = min(self.tokens, self.rate)  # Cap at bucket size
            self.last_refill = now
            
            if self.tokens >= 1:
                self.tokens -= 1
                return
            
            # Not enough tokens — wait until next token is available
            wait_time = (1 - self.tokens) / self.rate
            self.last_refill = time.monotonic()  # Update for accurate refill
            self.tokens = 0
        
        await asyncio.sleep(wait_time)
        await self.acquire()  # Retry after waiting

# Usage:
# limiter = RateLimiter(10)  # 10 requests per second
# async with session.get(url):
#     await limiter.acquire()
#     response = await session.get(url)
```
This implements a token bucket: tokens accumulate at the rate of `rate_per_second`, up to a maximum of `rate_per_second` tokens. Each request consumes a token. If no token is available, the request waits until one is refilled. The lock ensures the token count is updated atomically across concurrent coroutines. This is a common pattern for API clients that need to respect rate limits.

> [!question]- Q5. Explain the difference between `asyncio.create_task()`, `asyncio.ensure_future()`, and `loop.create_task()`. When would you use each?
**Answer:** `asyncio.create_task(coro)` (Python 3.7+) is the modern, recommended way — it wraps a coroutine in a Task and schedules it on the running event loop. It raises `RuntimeError` if no loop is running, making errors obvious. `asyncio.ensure_future(obj)` is older (Python 3.4+) — it accepts a coroutine, Future, or Task, and wraps/schedules it. It's more flexible but also more confusing — if you pass a Task, it returns the same Task. `loop.create_task(coro)` is the low-level method — it requires an explicit loop object. Use `asyncio.create_task()` for new code. Use `ensure_future()` when you need to accept either a coroutine or a Future. Avoid `loop.create_task()` unless you're managing the loop explicitly. In practice, `create_task` covers 99% of use cases.

## Related
[[gil-and-threading]]
[[multiprocessing]]
[[concurrency-patterns]]
[[context-managers]]
[[generators-and-iterators]]

#status/new