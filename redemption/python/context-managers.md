# Context Managers

## What it is
A context manager is an object that defines `__enter__` and `__exit__` methods, invoked when entering and exiting a `with` block. The pattern guarantees that setup and teardown code run reliably — even if an exception occurs inside the block. While file handling is the canonical example, context managers are a general resource-management pattern: database connections, locks, temporary directory changes, timing blocks, transaction boundaries, and anything that needs deterministic cleanup. This file covers the protocol, the `contextlib` decorators that make writing context managers trivial, and the subtle behaviors that distinguish correct from buggy implementations.

## Why it matters
The `with` statement is Python's answer to RAII (Resource Acquisition Is Initialization) in C++. Without it, you're writing `try/finally` blocks everywhere — and getting them wrong is easy. AI-generated code often forgets the `finally` or mishandles exception suppression. In interviews, being asked to implement a context manager from scratch tests whether you understand the protocol beyond `with open(...)`. And in production, a context manager that doesn't properly handle exceptions in `__exit__` can silently swallow errors or fail to release resources — both are production incidents waiting to happen.

## Core example

### The protocol — what `with` actually does

```python
# with cm as value:
#     do_something()

# Is equivalent to:
value = cm.__enter__()
try:
    do_something()
finally:
    cm.__exit__(exc_type, exc_value, traceback)

# The __exit__ method receives exception information if an exception
# occurred inside the with block, or None/None/None if no exception.
# If __exit__ returns True, the exception is suppressed.
# If it returns False (or None, the default), the exception propagates.
```

The critical detail: `__exit__` always runs — even if the `with` block returns, raises, or is interrupted. This is what makes context managers reliable for resource cleanup. The `try/finally` equivalent is correct but verbose; `with` makes the intent explicit and the execution guaranteed.

### Class-based context manager

```python
class Timer:
    def __init__(self, label):
        self.label = label
        self.start = None
        self.end = None

    def __enter__(self):
        import time
        self.start = time.time()
        return self  # This is what 'as' captures

    def __exit__(self, exc_type, exc_value, traceback):
        import time
        self.end = time.time()
        print(f"{self.label}: {self.end - self.start:.3f}s")
        # Return None (or False) — don't suppress exceptions
        return False

with Timer("processing") as t:
    total = sum(range(10_000_000))
# processing: 0.312s

# If an exception occurs inside the block, __exit__ still runs,
# and the exception propagates after __exit__ completes.
# The timer still records the duration up to the exception point.
```

### `contextlib.contextmanager` — the decorator approach

```python
from contextlib import contextmanager

@contextmanager
def timer(label):
    import time
    start = time.time()
    try:
        yield  # The value after 'as' goes here: yield self
        # Everything after yield is the __exit__ logic
    finally:
        end = time.time()
        print(f"{label}: {end - start:.3f}s")

# Usage identical to the class-based version:
with timer("processing"):
    total = sum(range(10_000_000))

# The contextmanager decorator converts a generator function into
# a context manager. The code before yield is __enter__.
# The code after yield (in finally) is __exit__.
# The yield value is what 'as' captures.

# This is almost always preferable to writing a class — it's more
# concise and the try/finally structure is explicit. The only reason
# to use a class is if you need the context manager to be reusable
# or to have additional methods.
```

### Yielding a value — the `as` clause

```python
@contextmanager
def managed_file(path, mode):
    f = open(path, mode)
    try:
        yield f  # This is what 'as f' captures
    finally:
        f.close()

# Without the yield value, 'as' would capture None.
# The yield can yield anything — a resource, a connection, a lock,
# or even a custom object with helper methods.

# Important: if __enter__ (the code before yield) raises an exception,
# the generator never reaches yield, and __exit__ code doesn't run.
# This is correct — you can't clean up a resource you never acquired.
```

### Exception handling in `__exit__` — suppressing vs propagating

```python
@contextmanager
def suppress_exception(*exc_types):
    try:
        yield
    except exc_types as e:
        print(f"Suppressed: {e}")
        # If we don't re-raise, the exception is suppressed
        # In a class-based __exit__, returning True has the same effect

# Usage:
with suppress_exception(ValueError):
    int("not a number")  # ValueError raised, caught, suppressed
print("continues normally")  # This runs

# If you want to log but still propagate:
@contextmanager
def log_exceptions():
    try:
        yield
    except Exception as e:
        print(f"Exception: {e}")
        raise  # Re-raise to propagate

# The key: in __exit__, returning True suppresses the exception.
# In a generator-based contextmanager, NOT re-raising suppresses it.
# Always be explicit about which behavior you want — silent suppression
# is a common source of bugs where errors disappear without a trace.
```

### Multiple context managers — nested `with`

```python
# You can chain multiple context managers on one line:
with open("input.txt") as infile, open("output.txt", "w") as outfile:
    data = infile.read()
    outfile.write(data)

# This is equivalent to:
with open("input.txt") as infile:
    with open("output.txt", "w") as outfile:
        data = infile.read()
        outfile.write(data)

# Both files are guaranteed to close, even if an exception occurs.
# The exit happens in reverse order of entry — outfile closes first,
# then infile. This is the correct order for nested resources.

# In Python 3.9+, you can also use contextlib.ExitStack for dynamic
# numbers of context managers (e.g., when you don't know at code
# write time how many files you'll open).
```

### `contextlib.ExitStack` — dynamic context managers

```python
from contextlib import ExitStack

# When you need to manage a variable number of context managers:
files = ["file1.txt", "file2.txt", "file3.txt"]
with ExitStack() as stack:
    handles = [stack.enter_context(open(f)) for f in files]
    # All files are guaranteed to close when the block exits
    # Even if opening one fails, previously opened files are closed

# ExitStack is also useful for cleanup callbacks:
with ExitStack() as stack:
    stack.callback(lambda: print("cleanup ran"))
    stack.callback(print, "another cleanup")
    # Callbacks run in LIFO order when exiting
```

### Real-world patterns — beyond files

```python
# Database transaction
@contextmanager
def transaction(db):
    try:
        yield
        db.commit()
    except Exception:
        db.rollback()
        raise

# Lock with timeout
@contextmanager
def timed_lock(lock, timeout=5):
    acquired = lock.acquire(timeout=timeout)
    if not acquired:
        raise TimeoutError(f"Could not acquire lock after {timeout}s")
    try:
        yield
    finally:
        lock.release()

# Temporary directory change
import os
from contextlib import contextmanager

@contextmanager
def cd(path):
    old_path = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old_path)

# Working with multiple resources that must all succeed or none:
@contextmanager
def atomic_write(path, temp_suffix=".tmp"):
    temp_path = path + temp_suffix
    f = open(temp_path, "w")
    try:
        yield f
        f.close()
        os.rename(temp_path, path)  # Atomic on POSIX
    except Exception:
        f.close()
        os.remove(temp_path)
        raise
```

## Common mistakes / gotchas

- **Forgetting `try/finally` in generator-based context managers** — if the code after `yield` isn't in a `finally` block, an exception inside the `with` block skips the cleanup. The `finally` is what guarantees `__exit__` runs.
- **Yielding more than once** — a context manager generator should yield exactly once. A second `yield` would turn the `with` body into a `send()` call, which is almost never what you want.
- **`__exit__` returning `True` suppresses ALL exceptions** — including `KeyboardInterrupt` and `SystemExit`. This can make your program unkillable. Only return `True` for specific, expected exception types.
- **Not handling `None` exception info in `__exit__`** — when no exception occurs, `__exit__` receives `(None, None, None)`. If your `__exit__` logic assumes exception info is always present, it will crash on normal exits.
- **Context managers are not reusable** — a class-based context manager's `__enter__` and `__exit__` are called once per `with` block. If you reuse the same instance, the `__exit__` from the first use runs, then `__enter__` runs again — but the state may be inconsistent. Generators created by `@contextmanager` are single-use by design.
- **`__enter__` raises → `__exit__` doesn't run** — if `__enter__` (or the code before `yield`) raises, there's nothing to clean up, so `__exit__` doesn't run. This is correct, but surprising if you expected cleanup to run regardless.
- **Confusing `contextlib.contextmanager` with `contextlib.ContextDecorator`** — `@contextmanager` creates a context manager for `with` statements. `ContextDecorator` creates a decorator that also works as a context manager. They serve different purposes.
- **Resource leaks when `__enter__` partially succeeds** — if `__enter__` acquires multiple resources and fails on the second, the first acquired resource leaks unless you handle it. Use `ExitStack` or nested `try/finally` to handle partial acquisition.

## Practice

> [!question]- Q1. Write a context manager `suppress(*exceptions)` that suppresses the given exception types. It should work like `contextlib.suppress` but implemented from scratch. Explain the mechanism.
**Answer:**
```python
from contextlib import contextmanager

@contextmanager
def suppress(*exceptions):
    try:
        yield
    except exceptions:
        pass  # Caught and not re-raised → suppressed
```
If no exceptions are given, `except ()` matches nothing, so nothing is suppressed — matching `contextlib.suppress()`'s behavior of raising `ValueError` if no exceptions are provided. The mechanism: the `except exceptions` tuple catches any of the listed exception types. Since we don't `raise` inside the except block, the exception is swallowed. The `yield` is the critical point — it's where the `with` body executes. If the body raises, control jumps to the `except` clause. If it doesn't raise, the `except` is skipped and the context manager exits normally.

> [!question]- Q2. Implement a context manager `retry_on_failure(max_attempts, delay)` that retries the entire `with` block up to `max_attempts` times on exception. What are the limitations of this approach?
**Answer:**
```python
import time
from contextlib import contextmanager

@contextmanager
def retry_on_failure(max_attempts, delay=0):
    last_error = None
    for attempt in range(max_attempts):
        try:
            yield
            return  # Success — exit the context manager
        except Exception as e:
            last_error = e
            if attempt < max_attempts - 1:
                time.sleep(delay)
    raise last_error
```
Limitations: (1) It retries the ENTIRE block — if the block has side effects before the failure, those side effects repeat on each retry. This makes it unsafe for non-idempotent operations. (2) It catches ALL exceptions — including `KeyboardInterrupt` and `SystemExit`, which probably shouldn't be retried. (3) The `yield` can only be called once in a generator context manager — but here we're calling it multiple times via the loop, which works because each iteration re-enters the `try` block. This is a valid use of the pattern but requires understanding that `yield` in a `with` context can be "re-entered" if the generator hasn't completed. The more common pattern is to retry the operation inside the block, not the block itself.

> [!question]- Q3. What happens if `__exit__` itself raises an exception? Which exception propagates?
**Answer:** If `__exit__` raises an exception, it REPLACES the original exception (if any). If the `with` block had an exception A, and `__exit__` raises exception B, then B propagates and A is lost. If the `with` block had no exception and `__exit__` raises B, then B propagates. This is why `__exit__` should be defensive — avoid operations that can fail (like I/O, logging to a file that might be full) or wrap them in try/except. If you must log in `__exit__`, use a bare `except` that doesn't re-raise. The principle: cleanup code should never mask the original error.

> [!question]- Q4. Design a context manager that measures both execution time AND peak memory usage of a block. Return both metrics through the `as` variable.
**Answer:**
```python
import time
import tracemalloc
from contextlib import contextmanager

@contextmanager
def profile():
    tracemalloc.start()
    start = time.perf_counter()
    try:
        yield  # No value to return — metrics are read after
    finally:
        end = time.perf_counter()
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        print(f"Time: {end - start:.3f}s")
        print(f"Peak memory: {peak / 1024 / 1024:.2f} MB")
```
To return metrics through `as`, yield a dict or a named tuple:
```python
from collections import namedtuple

ProfileResult = namedtuple("ProfileResult", ["time_seconds", "peak_memory_mb"])

@contextmanager
def profile():
    tracemalloc.start()
    start = time.perf_counter()
    try:
        result = ProfileResult(0, 0)  # Placeholder — will be updated
        yield result
    finally:
        end = time.perf_counter()
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        result.time_seconds = end - start
        result.peak_memory_mb = peak / 1024 / 1024
```
But this has a subtlety: the `result` object is yielded before the measurements are taken. The user accesses `result.time_seconds` AFTER the `with` block exits, by which point the `finally` has populated the fields. This works because the yielded object is a mutable reference — the `finally` block mutates it after the block body completes.

> [!question]- Q5. Explain why `contextlib.closing` exists and when you need it instead of a `with` statement directly.
**Answer:** `contextlib.closing` wraps an object that has a `.close()` method but isn't itself a context manager (doesn't have `__enter__` and `__exit__`). Some objects — like `urllib.request.urlopen()` results in older Python versions, or `subprocess.Popen` stdout pipes — have `.close()` but don't support `with` directly. `closing(obj)` creates a context manager that calls `obj.close()` on exit. In modern Python, most resource-supporting objects are already context managers, so `closing` is less needed. But it's still useful for third-party libraries that haven't adopted the protocol, or for objects where the close method has a different name — you can wrap them with a custom `@contextmanager` instead.

## Related
[[functions-and-scope]]
[[oop-and-dunder-methods]]
[[exception-handling]]
[[file-io]]
[[gil-and-threading]]

#status/new