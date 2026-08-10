# Performance Profiling

## What it is
Performance profiling is the systematic measurement of where your code spends time and memory. Python provides built-in tools (`cProfile`, `pstats`, `profile`, `timeit`, `time`) and third-party tools (`line_profiler`, `memory_profiler`, `py-spy`, `scalene`) that answer different questions: "which functions consume the most time" (cProfile), "which lines are slow" (line_profiler), "where is memory allocated" (memory profiler), and "what's the production CPU profile without restarting" (py-spy). This file covers the methodology — how to profile correctly, how to interpret results, and how to distinguish algorithmic bottlenecks from micro-optimizations that don't matter.

## Why it matters
Premature optimization is the root of all evil — but so is unoptimized code that runs 100x slower than it should. The difference between guessing ("I think the GIL is the problem") and knowing ("73% of time is spent in this JSON serialization call") is profiling. In interviews, performance questions test whether you understand the difference between O(n) and O(n²) bottlenecks, when to profile, and how to read a profile. For your ML work — training loops, data loading, inference — profiling is the difference between a pipeline that finishes in hours and one that finishes in days. The SOTA DINOv2 model you trained? Profiling identified the augmentation bottleneck and the data loader queuing issue. You already do this — this file formalizes the approach.

## Core example

### `cProfile` — the built-in function-level profiler

```python
import cProfile
import pstats
import io

# Profile a function:
def my_function():
    total = 0
    for i in range(1000000):
        total += i
    return total

# Method 1: Command line (no code changes)
# $ python -m cProfile -s cumulative myscript.py

# Method 2: In-code profiling
profiler = cProfile.Profile()
profiler.enable()
result = my_function()
profiler.disable()

# Print stats sorted by cumulative time:
s = io.StringIO()
ps = pstats.Stats(profiler, stream=s).sort_stats('cumulative')
ps.print_stats(20)  # Top 20 functions
print(s.getvalue())

# Output columns:
# ncalls: number of calls
# tottime: total time spent in the function (excluding subcalls)
# percall: tottime / ncalls
# cumtime: cumulative time (including subcalls)
# percall: cumtime / ncalls
# filename:lineno(function): where the function is defined

# Key metrics to focus on:
# - cumtime: functions with high cumulative time are on the critical path
#   — optimizing them (or their callees) has the biggest impact
# - tottime: functions with high tottime but low cumtime are doing
#   their own work — optimize the function itself
# - ncalls: functions called many times — even small per-call overhead
#   adds up. Consider caching or vectorization.

# The golden rule: optimize the functions with the highest cumtime
# first. They're where your program actually spends its time.
```

### Interpreting a cProfile output — what to look for

```python
# Sample output (simplified):
#    ncalls  tottime  percall  cumtime  percall filename:lineno(function)
#         1    0.000    0.000    5.234    5.234 main.py:1(<module>)
#       100    0.001    0.000    5.233    0.052 main.py:10(process_all)
#    1000000    2.100    0.000    2.100    0.000 main.py:25(process_item)
#         1    0.000    0.000    3.132    3.132 {built-in method json.dumps}
#       100    0.001    0.000    3.131    0.031 main.py:32(serialize)

# Analysis:
# - process_all takes 5.233s cumulative — it's the main bottleneck
# - process_item is called 1M times, taking 2.1s total — 40% of time
#   in this function itself (not subcalls)
# - json.dumps (via serialize) takes 3.132s — 60% of total time
#   but it's a built-in — you can't optimize it directly

# Action items:
# 1. Can you reduce the number of json.dumps calls? (batch serialization)
# 2. Can you use a faster JSON library? (orjson, ujson)
# 3. Can you reduce the data size before serialization?
# 4. process_item at 2.1s — can it be vectorized with NumPy?

# The profile tells you WHERE to optimize. The WHY and HOW require
# understanding the code. But without the profile, you'd be guessing
# whether to optimize process_item or json.dumps — and the profile
# says json.dumps is the bigger target.
```

### `line_profiler` — line-by-line timing

```python
# cProfile tells you which functions are slow. line_profiler tells you
# which LINES within a function are slow. Install: pip install line_profiler

# Decorate the function you want to profile:
from profile import profile

@profile  # This is available when running with kernel -l
def process_data(data):
    results = []
    for item in data:          # Line 10
        transformed = heavy_transform(item)  # Line 11 — slow?
        results.append(transformed)  # Line 12
    return results

# Run with: $ kernel -l myscript.py
# Output:
# Line #      Hits         Time  Per Hit   % Time  Line Contents
# ==============================================================
#   10                                           @profile
#   11                                           def process_data(data):
#   12         1          500     500      0.1      results = []
#   13     10000        10000       1      2.0      for item in data:
#   14      9999     4000000     400     97.5          transformed = heavy_transform(item)
#   15      9999        15000       1      0.4          results.append(transformed)
#   16         1          100     100      0.0      return results

# The 97.5% on line 14 is the clear bottleneck. The loop overhead
# (line 13) and append (line 15) are negligible. Optimize heavy_transform
# or replace it with a vectorized operation.

# line_profiler is essential when cProfile shows a function is slow
# but you need to know which part of the function to optimize.
# Don't use it on every function — only on the top bottlenecks
# identified by cProfile. It has overhead and slows execution 10-100x.
```

### `timeit` — benchmarking small code snippets

```python
import timeit

# timeit runs code many times and measures average execution time.
# It disables GC for more accurate measurements and runs multiple
# iterations to reduce noise.

# Compare two approaches:
setup = "from math import sqrt"

stmt1 = """
result = []
for i in range(1000):
    result.append(sqrt(i))
"""

stmt2 = """
result = [sqrt(i) for i in range(1000)]
"""

time1 = timeit.timeit(stmt1, setup=setup, number=10000)
time2 = timeit.timeit(stmt2, setup=setup, number=10000)

print(f"Loop + append: {time1:.3f}s")
print(f"List comprehension: {time2:.3f}s")
# List comprehension is typically 20-30% faster — it avoids the
# method lookup and function call overhead of list.append().

# timeit is for comparing small code snippets. It's NOT for profiling
# entire applications — use cProfile for that. The key advantage:
# it runs many iterations and gives you statistically meaningful
# averages, not a single noisy measurement.

# For your ML work: use timeit to compare data preprocessing approaches.
# E.g., PIL vs OpenCV for image loading, or different augmentation
# libraries. Run each 1000 times and compare the average.
```

### Memory profiling — where the bytes go

```python
# memory_profiler: pip install memory_profiler
# Measures line-by-line memory usage.

from memory_profiler import profile

@profile
def process_large_file(path):
    data = []  # Line 5
    with open(path) as f:  # Line 6
        for line in f:  # Line 7
            data.append(process(line))  # Line 8 — memory grows here
    return analyze(data)  # Line 9

# Run: $ python -m memory_profiler script.py
# Output:
# Line #    Mem usage    Increment  Occurrences   Line Contents
# ==============================================================
#  5     50.1 MiB     50.1 MiB           1   data = []
#  6     50.1 MiB      0.0 MiB           1   with open(path) as f:
#  7     50.1 MiB      0.0 MiB    1000001   for line in f:
#  8    150.1 MiB      0.1 MiB    1000000       data.append(process(line))
#  9    200.1 MiB     50.0 MiB           1   return analyze(data)

# Line 8 shows memory growing by 0.1 MiB per iteration — 100MB total.
# The fix: process incrementally instead of accumulating.

# For production memory profiling without restarting:
# Use tracemalloc (built-in) or py-spy (sampling profiler).

# tracemalloc example (from [[memory-management-and-gc]]):
import tracemalloc
tracemalloc.start()

# ... run code ...

snapshot = tracemalloc.take_snapshot()
top_stats = snapshot.statistics('lineno')
for stat in top_stats[:10]:
    print(stat)  # Shows where memory was allocated

tracemalloc.stop()

# tracemalloc has low overhead (~5-10%) and can be enabled in production
# to track memory growth over time. It's the recommended approach for
# detecting memory leaks in long-running processes.
```

### `py-spy` — production profiling without downtime

```bash
# py-spy is a sampling profiler written in Rust. It attaches to a
# running Python process without restarting it and without adding
# overhead (sampling, not instrumenting). This is the tool you use
# when production is slow and you need to know why NOW.

# Install: pip install py-spy (or download binary)

# Profile a running process:
$ py-spy top --pid 12345  # Live top-like view of CPU usage by function

# Record a flame graph:
$ py-spy record -o flame.svg --pid 12345  # Records for 10s, outputs SVG
# Open flame.svg in browser — interactive flame graph showing call stack
# and time spent in each function.

# Dump a single snapshot:
$ py-spy dump --pid 12345  # Shows current call stack of all threads

# Why py-spy over cProfile for production:
# - No code changes needed — attach to any running Python process
# - No restart needed — profile production without downtime
# - Low overhead (sampling, not instrumenting) — safe for production
# - Works with C extensions, subprocesses, and multi-threaded code
# - Flame graphs visualize the call stack intuitively

# For your FastAPI API in production: if latency spikes, attach py-spy,
# record 30 seconds, and the flame graph shows exactly which endpoint
# and which function is consuming CPU. No need to redeploy with profiling
# enabled. This is the gold standard for production debugging.
```

### The profiling methodology — how to do it right

```python
# Step 1: Measure before optimizing
# Don't guess. Run the code and measure baseline performance.
# Use time.time() for quick checks, cProfile for detailed analysis.

# Step 2: Profile to find the bottleneck
# Run cProfile or py-spy. Identify the top 1-3 functions by cumtime.
# These are your optimization targets.

# Step 3: Optimize the bottleneck
# Focus on the biggest bottleneck first (Amdahl's Law: optimizing
# a function that takes 10% of time can at most give 10% speedup,
# even if you make it instant). Optimize the 80% function first.

# Step 4: Measure after optimizing
# Run the same benchmark. Compare before/after. Did it actually improve?
# By how much? (If not, revert — optimization can make things slower.)

# Step 5: Repeat
# After optimizing the top bottleneck, profile again. The next bottleneck
# is now the top. Repeat until performance meets requirements.

# Common optimization strategies (in order of impact):
# 1. Algorithmic change — O(n²) → O(n log n) → 1000x+ improvement
# 2. Vectorization — Python loops → NumPy → 10-100x improvement
# 3. Caching — avoid recomputation → 2-10x improvement
# 4. I/O optimization — batch reads, async I/O → 2-10x improvement
# 5. Concurrency — threads/processes/async for parallelism → 2-8x improvement
# 6. Micro-optimization — local variable lookup, avoid attribute access
#    → <2x improvement (usually not worth it)

# The rule: 90% of performance gains come from algorithmic changes
# and vectorization. Micro-optimizations (the stuff AI-generated code
# obsesses over) rarely matter. Profile first, optimize the right thing,
# measure the improvement.
```

### Common performance anti-patterns

```python
# Anti-pattern 1: String concatenation in a loop
s = ""
for item in big_list:
    s += str(item)  # O(n²) — creates a new string each iteration
# Fix: s = "".join(str(x) for x in big_list)  # O(n)

# Anti-pattern 2: Repeated attribute lookup in a loop
for i in range(1000000):
    value = math.sqrt(i)  # Attribute lookup each iteration
# Fix: sqrt = math.sqrt; for i in range(1000000): value = sqrt(i)

# Anti-pattern 3: Using list when set is for membership
if x in my_list:  # O(n) — scans the list
# Fix: use a set: if x in my_set:  # O(1)

# Anti-pattern 4: Not using generators for large data
data = [process(x) for x in huge_list]  # Builds entire list in memory
# Fix: data = (process(x) for x in huge_list)  # Generator — lazy

# Anti-pattern 5: Synchronous I/O in async code
async def handler():
    data = requests.get(url)  # Blocks the event loop!
# Fix: data = await aiohttp.get(url)  # Non-blocking

# Anti-pattern 6: Pickling large objects repeatedly
# If you send the same large object to multiprocessing workers,
# pickle it once and share via shared memory or initializer.

# Anti-pattern 7: Global interpreter lock contention in threads
# For CPU-bound Python code, use processes not threads.
# For I/O-bound, threads or async are fine.

# The key insight: most of these anti-patterns are caught by profiling.
# You don't need to memorize them — profile, find the slow thing, fix it.
```

## Common mistakes / gotchas

- **Profiling in debug mode** — Python's debug mode (`python -d` or running with a debugger) can be 2-10x slower. Always profile with the same settings as production.
- **Profiling with small inputs** — a function that's fast on 10 items may be O(n²) and catastrophic on 10,000 items. Profile with realistic data sizes.
- **Optimizing without measuring** — "I think this will be faster" is almost always wrong. Measure before and after. If it's not faster, revert.
- **Ignoring I/O wait** — cProfile measures CPU time, not wall-clock time. If your program is I/O-bound (waiting for network/disk), cProfile shows low CPU usage but the program is slow. Use wall-clock time (`time.time()`) for I/O-bound code, and look at I/O wait with tools like `iostat` or `htop`.
- **Over-profiling** — running line_profiler on every function adds massive overhead. Use cProfile to find the top bottleneck, then line_profiler only on that function. Profile in layers.
- **Forgetting warm-up** — the first run of a function includes import time, JIT compilation (if using PyPy), and cold cache effects. Run the code a few times before measuring to get steady-state performance.
- **Micro-optimizations** — changing `len(x)` to a local variable or using `map()` over list comprehension saves nanoseconds. These don't matter unless they're in a hot loop identified by profiling. Focus on algorithmic improvements first.
- **Not considering the GIL** — profiling a multi-threaded CPU-bound Python program with cProfile shows time spent in each thread, but the GIL means they're not running in parallel. The total CPU time may be high but wall-clock time doesn't improve. Use multiprocessing for CPU-bound parallelism.

## Practice

> [!question]- Q1. A FastAPI endpoint that takes 50ms in development takes 2s in production. Describe your systematic approach to diagnose and fix this.
**Answer:** Step 1: Reproduce locally with production-like data (same DB size, same request patterns). If you can't reproduce, Step 2: Attach py-spy to the production process and record a flame graph during a slow request. The flame graph shows which functions consume CPU time. Step 3: Check if it's CPU-bound or I/O-bound — if CPU-bound, the flame graph shows Python functions; if I/O-bound, py-spy shows many threads waiting. Step 4: For I/O-bound, check database query times (slow query log), external API latency, and connection pool exhaustion. For CPU-bound, use cProfile locally with production data to identify the slow function. Step 5: Common causes: N+1 queries (check DB query count), missing indexes (check query plans), unbounded data fetching (SELECT * on large tables), synchronous I/O in async endpoints, or memory pressure causing swapping. Fix based on evidence from profiling — not guesses. The key: use py-spy in production for immediate diagnosis, then reproduce and profile locally for detailed analysis.

> [!question]- Q2. Your DINOv2 data loading pipeline processes 1000 images/second on a single core but you have 8 cores. The training loop is GPU-bound, but data loading is the bottleneck. Profile and optimize.
**Answer:** Profile the data loader with cProfile: run a training iteration and profile the DataLoader. Most likely bottlenecks: (1) Image loading from disk — I/O-bound, use more workers (num_workers > 0 in PyTorch DataLoader) to overlap disk I/O with GPU compute. (2) Image decoding — CPU-bound, C code (PIL/OpenCV), releases GIL — threads help. Use num_workers = num_cores. (3) Augmentation — if pure Python, it's GIL-bound — use C-based augmentations (Albumentations) or multiprocessing (num_workers). (4) Data transfer to GPU — use pin_memory=True for faster H2D transfer. (5) Collate function — if custom and slow, optimize it or use default collate. After optimizing each bottleneck, re-measure. The goal: data loading should be faster than GPU processing so the GPU never waits. If after optimization data loading is still the bottleneck, consider pre-processing the dataset once and storing processed images, or using a faster storage (NVMe SSD, RAM disk). The key: profile each component separately to identify which stage is the bottleneck, then optimize that stage specifically.

> [!question]- Q3. Compare `time.time()`, `time.perf_counter()`, `time.process_time()`, and `timeit.default_timer()`. When do you use each?
**Answer:** `time.time()` returns wall-clock time since epoch — affected by system time changes (NTP, manual adjustment). Use for logging timestamps, NOT for measuring durations. `time.perf_counter()` returns a monotonic clock with the highest available resolution — unaffected by system time changes. Use for measuring durations (the recommended choice). `time.process_time()` returns CPU time used by the current process — excludes time spent sleeping or waiting for I/O. Use for measuring CPU-bound work. `timeit.default_timer()` is `time.perf_counter()` on most platforms — it's what `timeit` uses internally. For benchmarking: `time.perf_counter()` for wall-clock duration, `time.process_time()` for CPU time, `timeit` for statistical benchmarking of small snippets. For production monitoring: `time.perf_counter()` for request latency (wall-clock), `time.process_time()` for CPU usage. Never use `time.time()` for durations — it can go backwards if the system clock is adjusted.

> [!question]- Q4. A function is called 10,000 times and takes 2 seconds total. cProfile shows 1.8s in a sub-function called by this function. You optimize the sub-function to take 0.2s. What's the expected total time after optimization? Explain using Amdahl's Law.
**Answer:** Before: function = 2.0s total, sub-function = 1.8s (90% of time), other = 0.2s. After: sub-function = 0.2s (optimized 9x), other = 0.2s (unchanged). New total = 0.2 + 0.2 = 0.4s. Speedup = 2.0 / 0.4 = 5x. Amdahl's Law: the maximum speedup is limited by the fraction of time that can be improved. Here, 90% of the time was in the sub-function. Even if we made it instant (0s), the best possible total would be 0.2s (the remaining 10%), giving a maximum speedup of 2.0 / 0.2 = 10x. Our 5x speedup is half the maximum — we improved the sub-function by 9x, not to zero. The lesson: optimizing the part that takes 90% of time gives big gains, but the remaining 10% becomes the new bottleneck. After this optimization, profile again — the "other" 0.2s is now 50% of the total, and may itself contain further optimization opportunities.

> [!question]- Q5. You have a script that processes a 10GB CSV file. It takes 30 minutes and uses 16GB of RAM. Design a profiling and optimization plan to reduce both time and memory.
**Answer:** Phase 1 — Profile memory: use tracemalloc or memory_profiler to identify where memory is used. Common issue: loading the entire CSV into a pandas DataFrame (10GB file → 16GB RAM due to DataFrame overhead). Fix: process in chunks (`pd.read_csv(chunksize=10000)`) or use a generator to process line by line. Phase 2 — Profile CPU: use cProfile to identify the slowest operation per chunk. Common issues: string parsing, type conversion, or per-row Python loops. Fix: vectorize with pandas/numpy operations, use faster CSV parsers (polars, which is written in Rust and uses less memory), or use PyArrow for zero-copy reads. Phase 3 — Profile I/O: check if disk read speed is the bottleneck. Fix: use SSD, read in larger chunks, or compress the CSV (gzip) and read with compression (less I/O, some CPU overhead for decompression). Phase 4 — Measure before/after each optimization. Expected results: chunked processing reduces memory from 16GB to <1GB (one chunk at a time), polars reduces time from 30min to ~5min (Rust implementation + SIMD), and compression reduces I/O time. The key: profile each dimension (memory, CPU, I/O) separately and optimize the bottleneck in each dimension. Don't optimize all at once — optimize, measure, then move to the next bottleneck.

## Related
[[gil-and-threading]]
[[multiprocessing]]
[[async-await-and-event-loop]]
[[concurrency-patterns]]
[[memory-management-and-gc]]
[[data-structures-and-complexity]]

#status/new