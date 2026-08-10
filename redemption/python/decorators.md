# Decorators

## What it is
A decorator is a callable that takes a function and returns a modified function (or callable). Syntactically, `@decorator` above a function is equivalent to `func = decorator(func)`. But the mechanics — preserving function metadata with `functools.wraps`, handling arguments with nested closures, creating stateful decorators with classes, and applying decorators to methods — reveal the patterns that separate working decorators from production bugs. This file covers both function-based and class-based decorators, with emphasis on the gotchas that AI-generated decorators consistently miss.

## Why it matters
Decorators are everywhere in Python — `@property`, `@staticmethod`, `@lru_cache`, FastAPI's `@app.get`, Django's `@login_required`. Writing your own decorators is a common interview task, and writing them *correctly* (preserving signatures, handling arguments, being thread-safe) is what distinguishes senior-level answers. The most common failure mode: a decorator that works for the simple case but breaks when applied to methods, when the decorated function has keyword-only arguments, or when multiple decorators stack. Understanding the mechanism means you can debug a broken decorator chain instead of guessing.

## Core example

### The minimal correct decorator

```python
from functools import wraps

def log_calls(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        print(f"Calling {func.__name__} with args={args}, kwargs={kwargs}")
        result = func(*args, **kwargs)
        print(f"{func.__name__} returned {result}")
        return result
    return wrapper

@log_calls
def add(a, b):
    return a + b

add(3, 5)
# Calling add with args=(3, 5), kwargs={}
# add returned 8

# Without @wraps, add.__name__ would be "wrapper" and add.__doc__ would be None.
# With @wraps, add retains its original name, docstring, annotations, and module.
```

### Decorators with arguments — the three-level nesting

```python
# A decorator that takes arguments needs an extra layer:
# decorator_factory(*args) → returns decorator → returns wrapper

def retry(max_attempts=3, delay=1):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    print(f"Attempt {attempt}/{max_attempts} failed: {e}")
                    if attempt < max_attempts:
                        import time
                        time.sleep(delay)
            raise last_error  # All attempts failed
        return wrapper
    return decorator

@retry(max_attempts=3, delay=0.5)
def flaky_api_call():
    import random
    if random.random() < 0.8:
        raise ConnectionError("timeout")
    return "success"

# The structure: retry(3, 0.5) returns the actual decorator function,
# which is then applied to flaky_api_call. This is why you need three levels.
```

The common mistake: forgetting that `@retry(max_attempts=3)` calls `retry(3)` first, which must return a decorator (a function that takes a function). If you write `@retry` without parentheses, `retry` itself is applied as the decorator directly — which works only if your decorator is designed to be used both with and without arguments.

### Class-based decorators — when you need state

```python
class CountCalls:
    def __init__(self, func):
        self.func = func
        self.calls = 0
        wraps(func)(self)  # Copy metadata to the instance

    def __call__(self, *args, **kwargs):
        self.calls += 1
        print(f"Call #{self.calls} to {self.func.__name__}")
        return self.func(*args, **kwargs)

@CountCalls
def greet(name):
    return f"Hello, {name}"

greet("Alice")  # Call #1
greet("Bob")    # Call #2
print(greet.calls)  # 2

# Class-based decorators are useful when you need mutable state that persists
# across calls. The instance is the decorator, and __call__ makes it callable.

# For methods, you need to handle the self/cls parameter:
class CountCallsMethod:
    def __init__(self, func):
        self.func = func
        self.calls = 0
        wraps(func)(self)

    def __call__(self, *args, **kwargs):
        self.calls += 1
        return self.func(*args, **kwargs)

# When applied to a method, the first argument is self (or cls),
# which gets passed through *args automatically. This works fine.
```

### Decorator stacking — order matters

```python
@decorator_a
@decorator_b
def func():
    pass

# This is equivalent to: func = decorator_a(decorator_b(func))
# The decorator closest to the function is applied FIRST.
# So decorator_b wraps func first, then decorator_a wraps the result.

# When calling func():
#   → decorator_a's wrapper runs
#     → decorator_b's wrapper runs
#       → original func runs

# This matters when decorators have side effects — the outermost decorator
# sees the call first and the return value last.
```

### Preserving signatures — `functools.wraps` vs manual

```python
# Without wraps, inspect.signature shows (*args, **kwargs)
# With wraps, it shows the original signature

import inspect

def simple_decorator(func):
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)
    return wrapper

@simple_decorator
def add(a: int, b: int) -> int:
    return a + b

print(inspect.signature(add))  # (*args, **kwargs) — lost all type info

# With wraps:
def good_decorator(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)
    return wrapper

@good_decorator
def add2(a: int, b: int) -> int:
    return a + b

print(inspect.signature(add2))  # (a: int, b: int) → int — preserved
```

This is critical for FastAPI and similar frameworks that use `inspect.signature` to auto-generate API docs and validate parameters. A decorator that doesn't preserve the signature breaks auto-documentation and type checking.

### Decorators on methods — the `self` problem

```python
class UserService:
    @log_calls
    def get_user(self, user_id):
        # When called as service.get_user(123), the decorator's wrapper
        # receives (service, 123) as args — self is passed automatically
        return {"id": user_id, "name": "Alice"}

# The wrapper in log_calls uses *args, **kwargs, so it handles self fine.
# But if the decorator had explicit parameters like def wrapper(a, b),
# it would break on methods because self becomes the first argument.

# For class methods and static methods, the order of decorators matters:
class MyClass:
    @classmethod
    @log_calls
    def cls_method(cls):
        pass

    @log_calls
    @classmethod
    def cls_method_wrong(cls):
        pass  # TypeError: 'classmethod' object is not callable

# The decorator closest to the function is applied first. @classmethod
# must be the innermost (closest to def) so it receives a raw function,
# not a wrapped function. The correct order: @classmethod above @decorator.
```

## Common mistakes / gotchas

- **Forgetting `@wraps`** — the decorated function loses its name, docstring, annotations, and signature. This breaks introspection, debugging, documentation generators, and type checkers.
- **Not using `*args, **kwargs` in the wrapper** — if the wrapper has explicit parameters, it can only decorate functions with that exact signature. Always use `*args, **kwargs` for generic decorators.
- **Decorator with arguments but missing a level** — `@retry(max_attempts=3)` requires `retry` to return a decorator. If `retry` itself is the decorator (no factory level), you get `TypeError: 'int' is not callable` or similar.
- **Decorators on methods without handling `self`** — a wrapper with explicit positional parameters breaks when applied to methods because `self` is passed as the first argument. Always use `*args, **kwargs`.
- **Stacking decorators in the wrong order** — `@decorator_a` above `@decorator_b` means `a` wraps `b`. For `@classmethod` and `@staticmethod`, they must be closest to the function definition.
- **Stateful decorators without thread safety** — a decorator that maintains a counter or cache is not thread-safe by default. If multiple threads call the decorated function simultaneously, the state can race. Use `threading.Lock` or `functools`' built-in thread-safe decorators.
- **Decorators that don't return the function's result** — a common typo is calling `func(*args, **kwargs)` but not returning the result. The decorated function then always returns `None`.
- **Applying decorators at import time** — decorators run when the module is imported, not when the function is called. If your decorator has side effects (e.g., registering the function in a global registry), those happen at import time.

## Practice

> [!question]- Q1. Write a `rate_limit` decorator that allows at most `max_calls` calls within a `window` seconds. Use a sliding window approach. What are the thread-safety considerations?
**Answer:**
```python
import time
from functools import wraps
from collections import deque
import threading

def rate_limit(max_calls, window):
    def decorator(func):
        calls = deque()
        lock = threading.Lock()

        @wraps(func)
        def wrapper(*args, **kwargs):
            with lock:
                now = time.time()
                # Remove calls outside the window
                while calls and calls[0] <= now - window:
                    calls.popleft()
                if len(calls) >= max_calls:
                    raise RuntimeError("Rate limit exceeded")
                calls.append(now)
            return func(*args, **kwargs)
        return wrapper
    return decorator
```
Thread safety: the `calls` deque is shared across all threads. Without the lock, two threads could both check `len(calls) < max_calls` simultaneously and both proceed, exceeding the limit. The lock ensures atomic check-and-append. However, this creates a bottleneck — all calls to any rate-limited function serialize on the lock. For high-throughput scenarios, consider a per-function lock or a more sophisticated token-bucket algorithm.

> [!question]- Q2. Write a `memoize` decorator that works with functions whose arguments may include unhashable types (lists, dicts). How do you handle this, and what are the trade-offs?
**Answer:** The standard approach is to convert unhashable arguments to a hashable representation. For lists, convert to tuples. For dicts, convert to sorted tuples of key-value pairs. But this requires recursively transforming the entire argument structure. A simpler but less efficient approach: skip caching for unhashable arguments and fall through to the function call. The trade-off: you lose caching for some calls but avoid the complexity of deep conversion. Alternatively, use `pickle.dumps` to serialize arguments into bytes (which are hashable) — but this is slow and changes the semantics for objects with custom `__reduce__`. The real answer: if your function takes unhashable arguments, memoization may not be the right optimization. Consider whether the function is even pure (same inputs → same outputs) before caching.

> [!question]- Q3. Explain why this decorator causes infinite recursion and how to fix it:
```python
def debug(func):
    def wrapper(*args, **kwargs):
        print(f"Calling {func.__name__}")
        return func(*args, **kwargs)
    return wrapper

@debug
def factorial(n):
    if n <= 1:
        return 1
    return n * factorial(n - 1)
```
**Answer:** No infinite recursion here — the recursion works correctly because `factorial` inside the function body refers to the wrapped function (the `wrapper`), and each recursive call goes through the wrapper, which calls the original `func`. This is actually fine — the counter from Q2 in [[functions-and-scope]] discussed this. The infinite recursion would occur if the wrapper called `func` but `func` was somehow rebound to the wrapper. The real issue with this decorator is that it counts every recursive call, not just top-level calls. If you wanted top-level-only logging, you'd need a depth counter or a `threading.local()` flag. The infinite recursion scenario happens when the decorator's wrapper accidentally references itself instead of the original function — typically through a closure capture bug.

> [!question]- Q4. Design a decorator that caches function results but automatically invalidates the cache when a specific module-level flag changes. How would you implement the invalidation mechanism?
**Answer:** The decorator maintains a cache dict and registers itself with a central invalidation registry. When the flag changes, it triggers invalidation callbacks:
```python
_cache_registry = set()

def invalidate_all_caches():
    for cache in _cache_registry:
        cache.clear()

def cache_with_invalidation(func):
    cache = {}
    _cache_registry.add(cache)
    @wraps(func)
    def wrapper(*args, **kwargs):
        if args not in cache:
            cache[args] = func(*args, **kwargs)
        return cache[args]
    return wrapper
```
A more targeted approach: pass a `cache_key_func` to the decorator that computes a version based on the flag. If the version changes, the cache key changes and the old cache is effectively invalidated. The trade-off: registry-based invalidation is simple but invalidates everything; versioned keys are more granular but require the flag to be incorporated into the cache key.

> [!question]- Q5. What's the difference between a decorator and a context manager? When would you choose one over the other for timing a function's execution?
**Answer:** A decorator wraps a function to modify its behavior at call time. A context manager wraps a block of code (`with` statement) to set up and tear down state. For timing: a decorator times the entire function call transparently. A context manager times a specific code block inside a function. Choose a decorator when you want to time every call to a function without modifying its body. Choose a context manager when you want to time a specific section of code, or when the setup/teardown logic needs to run around arbitrary code (not just a function call). You can also combine them: a context manager can be used inside a decorator, or a decorator can wrap a context manager usage.

## Related
[[functions-and-scope]]
[[oop-and-dunder-methods]]
[[context-managers]]
[[gil-and-threading]]

#status/new