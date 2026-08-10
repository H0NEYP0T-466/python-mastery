# Memory Management and GC

## What it is
Python's memory management is a hybrid system: reference counting (immediate, deterministic) plus a generational garbage collector (periodic, handles cycles). Every Python object has a reference count — when it reaches zero, the object is immediately freed. But reference counting can't handle reference cycles (A → B → A), which is where the generational GC comes in. The GC divides objects into three generations (0, 1, 2) based on how long they've survived, and collects younger generations more frequently — based on the observation that most objects die young. This file covers the mechanics of both systems, when each runs, how to detect and fix memory leaks, and the tools to profile memory usage.

## Why it matters
Memory leaks in Python are subtle — they're not the C-style "forgot to free" leaks but accidental object retention through caches, circular references, or global state. In long-running processes (web servers, ML training jobs, daemons), a slow memory leak leads to OOM kills after hours or days of operation. Understanding reference counting and the generational GC helps you reason about when objects are actually freed, why `__del__` is dangerous with cycles, and how to use `weakref` to avoid accidental retention. In interviews, memory management questions test whether you understand the mechanism beyond "Python has garbage collection."

## Core example

### Reference counting — the primary mechanism

```python
import sys

a = []         # refcount of [] = 1 (a points to it)
b = a          # refcount = 2 (a and b both point to it)
c = [a]        # refcount = 3 (a, b, and c[0] point to it)

print(sys.getrefcount(a))  # 4 — +1 because getrefcount itself creates a temp ref
# Note: getrefcount adds 1 for its own argument — the "real" count is 3

del b          # refcount = 3
c[0] = None    # refcount = 2 (a and c still point to it, but c[0] no longer)

# When refcount reaches 0, the object is immediately freed.
# This is deterministic — you know exactly when memory is reclaimed.
# This is why Python doesn't need a tracing GC for most objects.

# But reference counting has overhead: every assignment, attribute access,
# and function call involves incrementing and decrementing refcounts.
# This is part of why Python is slower than languages with simpler
# memory management (like Rust's compile-time ownership, or Go's GC).

# Reference counting CANNOT handle cycles:
class Node:
    def __init__(self):
        self.parent = None
        self.children = []

a = Node()
b = Node()
a.children.append(b)  # a → b
b.parent = a          # b → a — cycle!

# Even if you delete a and b:
del a
del b
# The refcount of both nodes is 1 (they point to each other), so they
# are NOT freed by reference counting. They're leaked — until the GC runs.
```

### The generational garbage collector — cleaning up cycles

```python
import gc

# The GC runs automatically when allocation thresholds are exceeded.
# You can also run it manually or disable it entirely.

# Three generations:
# - Generation 0: newly created objects — collected most frequently
# - Generation 1: survived one collection of gen 0 — collected less often
# - Generation 2: survived multiple collections — collected least often

# The heuristic: objects that have survived a long time are likely
# to keep surviving (the "weak generational hypothesis"). So collecting
# young objects frequently is cheap and effective; collecting old objects
# rarely is a good trade-off.

# Check thresholds:
print(gc.get_threshold())  # (700, 10, 10) — defaults
# Meaning: when 700 more objects are allocated than deallocated in gen 0,
# a gen 0 collection is triggered. After 10 gen 0 collections, a gen 1
# collection is triggered. After 10 gen 1 collections, a gen 2 collection.

# The GC tracks object allocations vs deallocations per generation.
# When the difference exceeds the threshold, a collection runs.

# Disable the GC (useful for performance-critical sections where you
# know you won't create cycles):
gc.disable()
# ... do work ...
gc.enable()

# Force a full collection:
collected = gc.collect()  # Returns number of objects collected
print(f"Collected {collected} objects")

# For your ML training: disabling the GC during tight training loops
# can improve performance by 5-10% (no GC interrupts), but you must
# manually collect at checkpoint boundaries or risk memory growth.
```

### `__del__` — the finalizer trap

```python
import gc

class Resource:
    def __init__(self):
        print("Resource created")
    
    def __del__(self):
        print("Resource cleaned up")

# Simple case — works fine:
r = Resource()
del r  # "Resource cleaned up" — refcount goes to 0, __del__ runs

# But with a cycle — __del__ is NOT called:
class Node:
    def __init__(self, name):
        self.name = name
        self.parent = None
    
    def __del__(self):
        print(f"Node {self.name} cleaned up")

a = Node("A")
b = Node("B")
a.parent = b  # Cycle: a → b → a (if b also references a)

del a
del b
# __del__ is NOT called — the cycle keeps refcount > 0
# The GC will eventually collect the cycle, but objects with __del__
# in cycles are NOT collected by the GC in Python 3.4+ (they're moved
# to gc.garbage instead) — this is a memory leak!

# The rule: avoid __del__. Use context managers instead.
# If you MUST use __del__, ensure the object can't be part of a cycle
# (e.g., don't create back-references, or use weakref for back-references).

# In Python 3.4+, the GC handles __del__ in cycles by finalizing them
# in a specific order, but it's complex and error-prone. The official
# recommendation: don't use __del__. Use context managers ([context-managers])
# or explicit close() methods.
```

### `weakref` — references that don't keep objects alive

```python
import weakref

# A weak reference doesn't increment the refcount. If the object has
# only weak references pointing to it, it can be garbage collected.

class MyClass:
    pass

obj = MyClass()
weak = weakref.ref(obj)  # Weak reference — doesn't keep obj alive

print(weak())  # Returns obj if still alive
del obj        # obj is freed (no strong references remain)
print(weak())  # None — object was collected

# Weak references are used for:
# 1. Caches that don't prevent keys/values from being collected
#    weakref.WeakValueDictionary — values are weakly referenced
#    When a value is no longer strongly referenced elsewhere, it's
#    automatically removed from the cache.

cache = weakref.WeakValueDictionary()
key = "expensive_obj"
value = ExpensiveObject()
cache[key] = value  # Weak reference to value

del value  # If no other strong references, value is collected
print(cache.get(key))  # None — automatically removed

# 2. Observer patterns — observers register weakly so they don't
#    prevent the subject from being collected.

# 3. Circular data structures — use weakref for back-references
#    to break cycles. In a tree, parent → child is strong,
#    child → parent is weak. This allows the tree to be collected
#    when the root is deleted.

class TreeNode:
    def __init__(self, value):
        self.value = value
        self.children = []
        self._parent = None  # Weak reference
    
    @property
    def parent(self):
        return self._parent() if self._parent else None
    
    @parent.setter
    def parent(self, p):
        self._parent = weakref.ref(p) if p else None
```

### Memory leaks — detection and common patterns

```python
import gc
import sys

# Common leak patterns in Python:

# 1. Unbounded caches / global lists/dicts
cache = {}  # Grows forever — never cleared
# Fix: use functools.lru_cache with maxsize, or WeakValueDictionary,
# or explicitly clear the cache periodically.

# 2. Event listeners / callbacks not unregistered
class EventSource:
    def __init__(self):
        self.listeners = []
    
    def add_listener(self, cb):
        self.listeners.append(cb)  # Listener keeps source alive AND
                                   # source keeps listener alive — leak
# Fix: use weakref for listeners, or explicitly remove listeners.

# 3. Threads that never exit
import threading
def worker():
    while True:
        pass  # Infinite loop — thread never exits
t = threading.Thread(target=worker)
t.daemon = True  # Without daemon, process won't exit
t.start()  # Thread runs forever — memory held by thread is never freed

# 4. Unclosed resources (files, sockets, DB connections)
# Even with the GC, resources may not be released promptly.
# Always use context managers.

# 5. Class-level mutable state
class RequestHandler:
    history = []  # Class-level list — shared across all instances
                  # Grows forever as instances are created
# Fix: use instance-level state, or bound the list.

# Detecting leaks:
# 1. Use gc.get_objects() to see all tracked objects
# 2. Take snapshots and compare
# 3. Use tracemalloc (Python 3.4+) for allocation tracking

import tracemalloc
tracemalloc.start()

# ... run code ...

current, peak = tracemalloc.get_traced_memory()
print(f"Current: {current / 1024 / 1024:.1f} MB, Peak: {peak / 1024 / 1024:.1f} MB")

# Get top memory allocations:
snapshot = tracemalloc.take_snapshot()
top_stats = snapshot.statistics('lineno')
for stat in top_stats[:10]:
    print(stat)

tracemalloc.stop()
```

### `__slots__` — reducing per-object memory

```python
# Every Python object has a __dict__ for attribute storage — this is
# ~100-200 bytes of overhead per object. For millions of objects,
# this adds up. __slots__ removes the __dict__ and uses fixed-size
# attribute storage.

class WithoutSlots:
    def __init__(self, x, y):
        self.x = x
        self.y = y
        # Each instance has a __dict__ — ~200 bytes overhead

class WithSlots:
    __slots__ = ['x', 'y']  # No __dict__ — attributes stored in fixed slots
    def __init__(self, x, y):
        self.x = x
        self.y = y

# Memory comparison:
import sys
print(sys.getsize(WithoutSlots(1, 2)))  # ~200+ bytes (varies by Python version)
print(sys.getsize(WithSlots(1, 2)))     # ~56 bytes — significant savings

# For 1 million objects: ~144 MB savings.

# Trade-offs of __slots__:
# - No dynamic attribute assignment (obj.new_attr = 5 → AttributeError)
# - No __dict__ (can't use vars(obj) to inspect attributes)
# - Multiple inheritance with conflicting __slots__ is complex
# - Pickling works but requires __getstate__/__setstate__ customization
# - Subclasses inherit __slots__ but can add their own

# Use __slots__ when:
# - You have many instances of a simple data class
# - Memory is a constraint
# - You don't need dynamic attributes
# - You're OK with the restrictions

# In Python 3.7+, consider dataclasses with slots=True:
from dataclasses import dataclass

@dataclass(slots=True)
class Point:
    x: float
    y: float
# Combines dataclass convenience with __slots__ memory efficiency.
```

### `malloc` and Python's allocator — the layer beneath

```python
# Python doesn't use the system malloc directly for small objects.
# It has its own memory allocator (pymalloc) optimized for small
# object allocation patterns (many small objects, short lifetimes).

# pymalloc:
# - Uses arenas (256KB each) divided into pools (4KB each)
# - Each pool manages objects of a specific size class (8, 16, 24, ... bytes)
# - This reduces fragmentation and improves allocation speed
# - Specialized for Python's object allocation patterns

# You can observe this:
import sys
print(sys.getallocatedblocks())  # Number of memory blocks allocated
# Useful for tracking memory usage over time — if this grows steadily,
# you have a leak.

# For C extensions: they can use Python's allocator (PyMem_Malloc) or
# the system malloc (malloc). Python's allocator is generally better
# for small objects because it integrates with Python's GC and has
# better caching behavior.

# In Python 3.11+, the allocator was further optimized with a new
# "free list" for small objects, reducing allocation overhead by ~10%.
```

## Common mistakes / gotchas

- **`__del__` with circular references** — objects with `__del__` in cycles are not collected by the GC (moved to `gc.garbage`). This is a memory leak. Avoid `__del__`; use context managers.
- **Unbounded caches** — a dict or list that grows without bound is the most common Python memory leak. Use `functools.lru_cache(maxsize=...)`, `WeakValueDictionary`, or explicit eviction.
- **Global mutable state** — module-level lists/dicts that accumulate data across requests in a long-running process. They're never GC'd because the module is always reachable.
- **Forgetting to close resources** — files, sockets, DB connections. Even with the GC, finalization is not prompt. Use context managers.
- **Closures capturing large objects** — a closure that captures a large object keeps it alive as long as the closure exists. Be careful with what you capture in lambdas and nested functions.
- **`sys.setrecursionlimit()` and deep recursion** — deep recursion uses stack frames, which consume memory. Hitting the recursion limit raises `RecursionError`, but before that, each frame consumes memory. For deep recursion, use iteration or `sys.setrecursionlimit()` with caution.
- **`gc.disable()` without re-enabling** — disabling the GC for performance without re-enabling it (or manually collecting) leads to unbounded memory growth from unfreed cycles. Use as a context manager: `with disabled_gc(): ...`.
- **`weakref` to mutable objects** — `weakref.ref` only works on objects that support weak references (most objects do, but lists, dicts, and some built-ins don't). Use `weakref.WeakValueDictionary` for caches — it handles this internally.

## Practice

> [!question]- Q1. You have a web server that processes requests and caches results. After running for a few hours, memory grows unbounded. The cache uses a plain dict: `cache[key] = result`. Diagnose and fix.
**Answer:** The plain dict cache grows unbounded because entries are never removed. Even if keys are no longer referenced elsewhere, the cache dict holds strong references to both keys and values, preventing garbage collection. Three fixes: (1) Use `functools.lru_cache(maxsize=1000)` for function result caching — automatically evicts least-recently-used entries. (2) Use `weakref.WeakValueDictionary` for the cache — values are weakly referenced, so when no other strong references exist, they're automatically removed. But this only works if the keys are also not strongly referenced elsewhere. (3) Use a TTL-based cache like `cachetools.TTLCache` — entries expire after a set time. The best choice depends on the access pattern: LRU for hot data, TTL for time-sensitive data, weakref for data that should live as long as something else references it. For a web server caching API responses, `cachetools.TTLCache(maxsize=1000, ttl=300)` is appropriate — bounded size + time-based expiration.

> [!question]- Q2. Explain why this class has a memory leak and fix it:
```python
class EventBus:
    def __init__(self):
        self._handlers = {}
    
    def register(self, event, handler):
        self._handlers.setdefault(event, []).append(handler)
    
    def emit(self, event, *args):
        for handler in self._handlers.get(event, []):
            handler(*args)
```
**Answer:** The `_handlers` dict holds strong references to all registered handlers. If a handler is a bound method (e.g., `obj.method`), it holds a reference to `obj`. Even if `obj` is no longer used elsewhere, the event bus keeps it alive through the handler reference. This is a classic observer-pattern leak. Fix: use weak references for handlers. `weakref.WeakMethod` for bound methods, `weakref.ref` for functions. When the referenced object is collected, the weak reference returns None, and you can clean up the handler list. Alternatively, use the `blinker` library or `pyee` which implement weak-reference event buses. The key insight: the event bus should not prevent its subscribers from being garbage collected.

> [!question]- Q3. You're training a DINOv2 model and notice memory grows steadily over epochs, even though you delete tensors and call `torch.cuda.empty_cache()`. What are the possible causes in Python (not PyTorch-specific), and how would you diagnose?
**Answer:** Python-side causes: (1) Training loop accumulates metrics/logs in a list that's never cleared — e.g., `losses.append(loss)` without periodic clearing or bounding. (2) Logger or callback holds references to old batches/epochs. (3) Caching in data loaders — if the dataset uses an unbounded cache. (4) Closures in the training loop capturing large objects (e.g., the entire model or dataset). (5) GC not running frequently enough — cycles from the training graph accumulate. Diagnosis: use `tracemalloc` to track Python memory allocations over time — take snapshots every epoch and compare. Use `gc.get_objects()` to count object types — if a specific type grows, that's the leak. Use `gc.collect()` manually at epoch boundaries to force collection and see if memory drops (if yes, the GC was just not running frequently enough). The fix: use bounded data structures for logs, clear callbacks between epochs, ensure no closures capture unnecessary objects, and run `gc.collect()` at checkpoint boundaries.

> [!question]- Q4. What is the difference between `gc.collect()` and `del obj` in terms of when memory is freed? Give an example where one works and the other doesn't.
**Answer:** `del obj` decrements the reference count of the object. If the refcount reaches zero, the object is immediately freed — this is deterministic and happens synchronously. `gc.collect()` runs the generational garbage collector, which identifies and frees objects that are part of reference cycles (refcount > 0 but unreachable). Example where `del` works but `gc.collect()` is unnecessary: `a = [1, 2, 3]; del a` — the list's refcount drops to 0 and it's immediately freed. No cycle exists, so the GC isn't needed. Example where `del` doesn't work but `gc.collect()` does: two objects referencing each other (cycle). `del a; del b` decrements refcounts but they stay > 0 (each references the other). The objects are unreachable but not freed until `gc.collect()` runs (or the GC auto-triggers). The key insight: `del` is for reference-counted objects; `gc.collect()` is for cyclic objects. Most Python objects are freed by `del` (refcount reaching 0); the GC is a backup for cycles.

> [!question]- Q5. Explain why `sys.getrefcount(obj)` returns a number one higher than you'd expect, and why this matters for debugging reference issues.
**Answer:** `sys.getrefcount(obj)` creates a temporary reference to `obj` as its argument, incrementing the refcount by 1 for the duration of the call. So if you see `getrefcount(a) == 3`, the "real" refcount is 2 (the extra 1 is from the function argument). This matters because when debugging reference issues, you must account for this offset. If you're checking whether an object will be freed when you `del` a variable, and `getrefcount` returns 2, the actual count is 1 — so `del` will free it. If you forget the offset, you might think an object has an extra reference when it doesn't. The offset is consistent and documented, but it's a common source of confusion when first debugging reference counts. The real use of `getrefcount` is for relative comparisons (before/after an operation) rather than absolute values.

## Related
[[oop-and-dunder-methods]]
[[context-managers]]
[[gil-and-threading]]
[[concurrency-patterns]]
[[performance-profiling]]

#status/new