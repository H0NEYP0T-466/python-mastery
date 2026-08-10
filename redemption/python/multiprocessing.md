# Multiprocessing

## What it is
Python's `multiprocessing` module sidesteps the GIL by spawning separate OS processes, each with its own Python interpreter, memory space, and GIL. This enables true parallelism for CPU-bound Python code — multiple processes run on multiple cores simultaneously. But this comes at a cost: processes don't share memory by default, so inter-process communication (IPC) requires explicit mechanisms (queues, pipes, shared memory). This file covers the process creation models (spawn vs fork vs spawn), shared memory, process pools, and the trade-offs between threading and multiprocessing that determine which to use.

## Why it matters
Multiprocessing is the answer to "how do I make Python CPU-bound code run faster on multiple cores." But it's not a drop-in replacement for threading — the memory model is fundamentally different, and misuse leads to pickling errors, memory bloat, and zombie processes. In interviews, multiprocessing questions test whether you understand the process model, IPC mechanisms, and when to choose processes over threads. For your ML work — data preprocessing, hyperparameter search, running multiple experiments — multiprocessing is the practical tool that turns a 4-hour job into a 1-hour job on a 4-core machine.

## Core example

### Spawn vs fork vs spawn — process creation models

```python
import multiprocessing as mp

# Three ways to start a process:
# 1. fork (Linux default) — child process copies the parent's memory
#    space via copy-on-write. Fast, but can be unsafe with threads.
# 2. spawn (Windows, macOS default, and Linux option) — starts a fresh
#    Python interpreter, re-imports the main module, and only passes
#    necessary data via pickling. Slower but safer.
# 3. spawn-fork — like spawn but inherits some resources. Rarely used.

# The start method matters because it affects what data is available
# in the child process and how fast process creation is.

# Check available methods:
print(mp.get_all_start_methods())  # ['fork', 'spawn', 'forkserver']
print(mp.get_start_method())       # Current method

# Set explicitly (must be done before any process creation):
# mp.set_start_method('spawn')

def worker(x):
    return x * x

# Using fork (Linux):
# Child inherits parent's memory — large data structures are available
# without explicit passing (copy-on-write means they're not actually
# copied unless modified). This is fast but can cause issues if the
# parent has threads or holds locks.

# Using spawn (cross-platform):
# Child starts fresh — only data passed via arguments is available.
# All arguments must be picklable. This is slower but safer and works
# on Windows and macOS.

# The key difference: with fork, global variables in the parent are
# visible in the child. With spawn, they're not — you must pass
# everything explicitly as arguments.

# Example showing the difference:
data = [1, 2, 3]  # Global variable

def use_global():
    # With fork: data is visible (inherited from parent)
    # With spawn: NameError — data doesn't exist in child
    try:
        return data
    except NameError:
        return "not available"

# With fork: works. With spawn: fails.
# The fix for spawn: pass data explicitly as arguments.
```

### Basic process creation

```python
import multiprocessing as mp
import os

def worker(num):
    print(f"Worker {num} running in PID {os.getpid()}")
    return num * num

if __name__ == "__main__":
    # The __main__ guard is REQUIRED on Windows (spawn) and strongly
    # recommended everywhere. Without it, the spawn method re-imports
    # the module and recursively creates infinite processes.
    
    p = mp.Process(target=worker, args=(5,))
    p.start()  # Spawns the process
    p.wait()   # Wait for completion
    # Note: Process doesn't have a return value directly.
    # Use Queue or Pipe to get results back.
```

### Process pools — the practical way to use multiprocessing

```python
import multiprocessing as mp

# Creating and managing processes manually is error-prone.
# Pool abstracts this — creates a worker process pool and distributes tasks.

def square(x):
    return x * x

if __name__ == "__main__":
    # Pool with 4 processes (default: cpu_count())
    with mp.Pool(processes=4) as pool:
        # map: blocks until all results are ready
        results = pool.map(square, range(10))
        print(results)  # [0, 1, 4, 9, 16, 25, 36, 49, 64, 81]

        # imap: returns results as they complete (ordered)
        for result in pool.imap(square, range(10)):
            print(result)  # Yields 0, 1, 4, 9, ... as they finish

        # imap_unordered: returns results as they complete (faster, unordered)
        for result in pool.imap_unordered(square, range(10)):
            print(result)

        # apply_async: submit a single task, get AsyncResult immediately
        async_result = pool.apply_async(square, (10,))
        result = async_result.get()  # Blocks until result is ready
        # async_result.get(timeout=5) — raises TimeoutError if not ready

        # map_async: async version of map
        async_results = pool.map_async(square, range(10))
        results = async_results.get()  # Blocks until all done

    # Pool context manager ensures processes are cleaned up
    # Without 'with', you must call pool.close() and pool.join()
```

### Inter-process communication — Queue and Pipe

```python
import multiprocessing as mp

# Processes don't share memory. To communicate, use Queue or Pipe.

# Queue — thread and process safe, FIFO
def producer(queue):
    for i in range(5):
        queue.put(i)
    queue.put(None)  # Sentinel to signal completion

def consumer(queue):
    while True:
        item = queue.get()
        if item is None:
            break
        print(f"Got: {item}")

if __name__ == "__main__":
    q = mp.Queue()
    p = mp.Process(target=producer, args=(q,))
    c = mp.Process(target=consumer, args=(q,))
    p.start()
    c.start()
    p.join()
    c.join()

# Pipe — two-way communication between two processes
# Faster than Queue for point-to-point communication
def sender(conn):
    conn.send("hello")
    conn.send([1, 2, 3])
    conn.close()

def receiver(conn):
    print(conn.recv())  # "hello"
    print(conn.recv())  # [1, 2, 3]
    conn.close()

if __name__ == "__main__":
    parent_conn, child_conn = mp.Pipe()  # Duplex by default
    p = mp.Process(target=sender, args=(child_conn,))
    r = mp.Process(target=receiver, args=(parent_conn,))
    p.start()
    r.start()
    p.join()
    r.join()

# Queue vs Pipe:
# - Queue: multiple producers/consumers, FIFO, slightly slower
# - Pipe: two endpoints only, faster, bidirectional
# - For most use cases with Pool, you don't need either — results
#   are returned through map/apply_async
```

### Shared memory — avoiding pickling overhead

```python
# For Python 3.8+, shared memory allows processes to share data
# without pickling. This is useful when you have large data that
# needs to be read by multiple processes.

from multiprocessing import shared_memory
import numpy as np

if __name__ == "__main__":
    # Create a shared memory block
    arr = np.array([1, 2, 3, 4, 5])
    shm = shared_memory.SharedMemory(create=True, size=arr.nbytes)
    
    # Create a numpy array backed by shared memory
    shared_arr = np.ndarray(arr.shape, dtype=arr.dtype, buffer=shm.buf)
    shared_arr[:] = arr[:]  # Copy data into shared memory
    
    # Now child processes can access the same memory without copying
    # by attaching to the shared memory by name
    
    # Clean up:
    shm.close()
    shm.unlink()  # Destroys the shared memory block

# For older Python or simpler cases, use mp.Array or mp.Value:
# arr = mp.Array('d', [1.0, 2.0, 3.0])  # Shared array of doubles
# counter = mp.Value('i', 0)             # Shared integer

# Shared memory is useful when:
# - You have large read-only data needed by all workers
# - Pickling the data for each task is expensive
# - Workers need to write results back to shared structures

# But: shared memory requires synchronization (locks) for writes,
# and the complexity often isn't worth it unless you've measured
# that pickling is the bottleneck.
```

### Common multiprocessing gotchas — and how to avoid them

```python
# GOTCHA 1: Pickling errors
# All arguments to worker functions must be picklable.
# Lambda functions, nested functions, and closures can't be pickled.

def outer():
    def inner(x):  # Can't be pickled — nested function
        return x * x
    return inner

# pool.map(outer(), range(10))  # PicklingError!

# Fix: use a top-level function or a class with __call__:
def square(x):  # Top-level — picklable
    return x * x

# GOTCHA 2: Memory usage
# Each process has its own Python interpreter and memory space.
# 8 processes = ~8x the memory of a single process (plus shared data).
# If each process loads a 1GB model, 8 processes = 8GB RAM.
# Solution: load models in child processes after fork (using initializer),
# or use shared memory for read-only data.

# GOTCHA 3: Daemon processes
# By default, processes are not daemon — the parent waits for them.
# If the parent exits while child processes are running, they become
# orphans. Use daemon=True for fire-and-forget tasks, but ensure
# proper cleanup.

# GOTCHA 4: Exception handling in workers
# Exceptions in worker processes are re-raised in the parent when
# you call .get() on the AsyncResult. But if you don't call .get(),
# the exception is silently swallowed. Always handle or check results.

async_result = pool.apply_async(worker, args)
try:
    result = async_result.get()
except SomeException as e:
    # Handle the exception that occurred in the worker
    ...

# GOTCHA 5: Process startup overhead
# Spawn method takes ~100-500ms per process to start. For quick tasks,
# the startup overhead dominates. Use Pool to amortize the cost —
# create once, reuse for many tasks.
```

### Initializer — sharing expensive setup across workers

```python
import multiprocessing as mp

# If each worker needs expensive setup (loading a model, connecting to DB),
# don't do it in the worker function — it runs for every task.
# Use initializer to run once per worker process.

def init_worker():
    """Called once when each worker process starts"""
    global model
    model = load_heavy_model()  # Load once per process

def process_item(item):
    global model
    return model.predict(item)

if __name__ == "__main__":
    with mp.Pool(processes=4, initializer=init_worker) as pool:
        results = pool.map(process_item, items)
    
    # Each of the 4 processes calls init_worker() once on startup.
    # The model is loaded 4 times total (once per process), not 4×N times.
    # This is the standard pattern for model serving with multiprocessing.
```

### Threading vs multiprocessing — when to use which

```python
# Decision framework:

# Use threading when:
# - I/O-bound workload (network, file, database)
# - Tasks involve waiting (latency-bound)
# - Shared state is needed (threads share memory naturally)
# - Memory is constrained (threads share the same process memory)
# - Using C extensions that release the GIL (NumPy, etc.)

# Use multiprocessing when:
# - CPU-bound pure Python workload
# - True parallelism is needed across multiple cores
# - Memory is not a constraint (each process has its own memory)
# - Isolation is needed (one process crashing doesn't kill others)
# - The task can be pickled and sent to workers

# Use asyncio when:
# - High-concurrency I/O (thousands of connections)
# - You need fine-grained control over concurrency
# - The workload is I/O-bound with cooperative multitasking
# - Memory is constrained (async is lighter than threads)

# For your ML work specifically:
# - Data loading with disk I/O → threading or multiprocessing (PyTorch DataLoader)
# - Hyperparameter search → multiprocessing (each trial is independent)
# - Model training → single process (training loops are usually optimized in C/CUDA)
# - Batch inference → multiprocessing (multiple processes run inference in parallel)
# - Model serving → async (many concurrent requests) or multiprocessing (CPU-bound inference)
```

## Common mistakes / gotchas

- **Missing `if __name__ == "__main__":`** — required on Windows (spawn) and causes infinite process recursion. Always wrap process creation in this guard.
- **Pickling errors with lambdas and closures** — worker functions and their arguments must be picklable. Use top-level functions.
- **Memory explosion** — each process copies the parent's memory (fork) or starts fresh (spawn). Large data in the parent = large memory per process. Use shared memory or lazy loading in workers.
- **Not closing pools** — `Pool` creates worker processes that persist. Always use `with` context manager or call `pool.close()` + `pool.join()`. Leaked processes become zombies.
- **Exceptions swallowed in workers** — if you don't call `.get()` on an `AsyncResult`, exceptions in the worker are never raised in the parent. Always retrieve results.
- **Using global variables with spawn** — spawn doesn't inherit globals. Pass data explicitly as arguments. With fork, globals are inherited but copy-on-write — modifications don't affect the parent.
- **Queue deadlock** — if a Queue fills up (default maxsize is unlimited, but if you set one), producers block. If all processes are blocked waiting, deadlock. Use appropriate buffer sizes or `put_nowait` with error handling.
- **Process startup overhead** — spawning processes takes time. For quick tasks, the overhead dominates. Use `Pool` to amortize the cost across many tasks.

## Practice

> [!question]- Q1. You have a list of 1000 images and need to run DINOv2 inference on each. Each inference takes ~50ms on CPU. Design a multiprocessing solution that maximizes throughput while minimizing memory usage. What are the bottlenecks?
**Answer:** Use a `Pool` with `initializer` to load the model once per worker process. Use `imap_unordered` for results as they arrive. Set `processes` to the number of CPU cores (or slightly more if I/O is involved). Memory: each process loads the model (~100MB for DINOv2), so 8 processes = 800MB. If this is too much, reduce process count or use shared memory for the model weights. Bottleneck: model loading time (amortized by initializer) and inference speed (CPU-bound). If inference is the bottleneck, adding more processes beyond core count doesn't help — they compete for CPU. If disk I/O (reading images) is the bottleneck, add more processes to overlap I/O with computation. The optimal configuration is determined by profiling: measure I/O time vs compute time and balance the process count accordingly.

> [!question]- Q2. Explain why this code fails on Windows but works on Linux, and how to fix it:
```python
import multiprocessing as mp

def worker(x):
    return x * x

pool = mp.Pool(4)
results = pool.map(worker, range(10))
print(results)
```
**Answer:** On Windows, the default start method is `spawn` — the child process re-imports the main module. Without the `if __name__ == "__main__":` guard, the re-import creates a new `Pool`, which spawns more children, which re-import, creating infinite recursion. On Linux, the default is `fork` — the child inherits the parent's state without re-importing, so the code works (though it's still bad practice). Fix: wrap the pool creation and usage in `if __name__ == "__main__":`. This ensures that when the module is re-imported by child processes, the pool creation code doesn't run. This is required on Windows and macOS (both use spawn), and strongly recommended on Linux for portability.

> [!question]- Q3. You need to process a 100GB dataset with 8 worker processes. The parent process has already loaded a 5GB data structure. Compare fork vs spawn in terms of memory usage and startup time. Which do you choose and why?
**Answer:** With fork (Linux): the child processes inherit the parent's 5GB data structure via copy-on-write. Memory: initially, all 8 processes share the same physical pages — total ~5GB + overhead. If workers modify the data, copy-on-write kicks in and each modification creates a private copy. Startup: fork is very fast (~milliseconds) because it just copies page tables. With spawn: each child starts fresh — the 5GB data is NOT inherited. You must pass it explicitly via pickling (slow, 5GB × 8 = 40GB of pickled data transferred) or reload it in each worker (5GB × 8 = 40GB RAM). Startup: spawn is slow (~500ms per process) plus pickling time. Choice: if the data is read-only and you're on Linux, fork is dramatically better — fast startup, shared memory. If you need cross-platform compatibility or the data is modified by workers, spawn with lazy loading in workers (each worker loads its own copy on demand) is the safer choice. For a 100GB processing pipeline, the fork approach on Linux is standard — use `multiprocessing.set_start_method('fork')` explicitly.

> [!question]- Q4. Design a worker pool that processes tasks from a queue, supports graceful shutdown on SIGTERM, and reports progress. What are the edge cases?
**Answer:**
```python
import multiprocessing as mp
import signal
import time
from itertools import count

running = True

def signal_handler(sig, frame):
    global running
    print("Received shutdown signal...")
    running = False

def worker(task_queue, result_queue, worker_id):
    signal.signal(signal.SIGTERM, signal_handler)
    while running:
        try:
            task = task_queue.get(timeout=1)  # Timeout to check running flag
            if task is None:  # Poison pill
                break
            result = process(task)
            result_queue.put(result)
        except mp.queues.Empty:
            continue  # Check running flag
    print(f"Worker {worker_id} exiting")

if __name__ == "__main__":
    signal.signal(signal.SIGTERM, signal_handler)
    task_queue = mp.Queue()
    result_queue = mp.Queue()
    
    workers = []
    for i in range(4):
        w = mp.Process(target=worker, args=(task_queue, result_queue, i))
        w.start()
        workers.append(w)
    
    # Feed tasks...
    # On SIGTERM, running=False, workers check and exit gracefully
    
    for w in workers:
        w.join(timeout=5)
        if w.is_alive():
            w.terminate()  # Force kill if not responding
            w.join()
```
Edge cases: (1) Workers stuck in a blocking operation that doesn't check the running flag — use timeouts on blocking calls. (2) Tasks in progress when SIGTERM arrives — decide whether to complete or abandon. (3) Result queue fills up — use `put` with timeout or a separate result consumer. (4) Worker crashes — monitor with `is_alive()` and respawn if needed. (5) Poison pills — send `None` for each worker to signal clean shutdown. (6) Zombie processes — always `join()` after `terminate()`.

> [!question]- Q5. Explain the difference between `multiprocessing.Pool`, `concurrent.futures.ProcessPoolExecutor`, and manual `Process` creation. When would you choose each?
**Answer:** `multiprocessing.Pool` is the classic API — `map`, `apply_async`, `imap`, etc. It gives fine-grained control over task submission and result retrieval. `concurrent.futures.ProcessPoolExecutor` is a higher-level API — `submit` returns `Future` objects, `map` is simpler. It's part of the standard `concurrent.futures` module, which has the same interface for `ThreadPoolExecutor` — making it easy to switch between threads and processes. Manual `Process` creation gives the most control — you manage process lifecycle, IPC (Queue/Pipe), and error handling yourself. Choose `Pool` when you want a simple worker pool with good control. Choose `ProcessPoolExecutor` when you want a cleaner API and potential compatibility with thread pools. Choose manual `Process` when you need custom IPC, process groups, or fine-grained lifecycle control. For most use cases, `Pool` or `ProcessPoolExecutor` is sufficient. Manual processes are for advanced scenarios.

## Related
[[gil-and-threading]]
[[async-await-and-event-loop]]
[[concurrency-patterns]]
[[memory-management-and-gc]]
[[context-managers]]

#status/new