# Functions and Scope

## What it is
Python functions are first-class objects — they can be passed around, returned, assigned, and have attributes. But the mechanics of how they capture variables (closures), how argument passing works (it's not "pass by value" and not "pass by reference"), and how name resolution behaves (LEGB rule with late binding) are the source of some of the most subtle bugs in Python code. This file covers the mechanism, not the syntax.

## Why it matters
The "mutable default argument" bug (covered in [[redemption/python/basics]]) is just the tip of the iceberg. Closures that capture variables by reference rather than value cause loop-variable bugs in decorators and callbacks. Understanding exactly how `*args` and `**kwargs` work at the call-site level matters for writing decorators that preserve signatures. And knowing that Python's argument passing is "pass by object reference" (or "call by sharing") prevents the confusion that leads to defensive copying everywhere — or worse, no copying where it's needed.

## Core example

### Argument passing — it's not pass-by-value or pass-by-reference

```python
def modify(x):
    x.append(1)       # mutates the object — caller sees the change
    x = [9, 9, 9]     # rebinds local name — caller does NOT see this

a = [1, 2, 3]
modify(a)
print(a)  # [1, 2, 3, 1] — the append was visible, the reassignment was not

# The model: Python passes references to objects, but the reference itself
# is passed by value. The function gets a copy of the reference, pointing
# to the same object. Mutating the object is visible. Rebinding the local
# name is not.

# This is sometimes called "call by sharing" — the caller and callee
# share the same object initially, but rebinds are local.
```

The practical rule: if you mutate the object (`.append()`, `d['k'] = v`, `obj.attr = x`), the caller sees it. If you rebind the parameter name (`x = something`), the caller doesn't. There's no "pass by value" for primitives — integers are immutable, so `x += 1` creates a new integer and rebinds, which the caller never sees.

### Closures and late binding — the classic loop bug

```python
# Creating 10 functions that each should return their own i
funcs = []
for i in range(10):
    funcs.append(lambda: i)

print([f() for f in funcs])
# [9, 9, 9, 9, 9, 9, 9, 9, 9, 9] — NOT [0, 1, 2, ..., 9]

# Why: each lambda captures the NAME i, not the value.
# By the time any lambda is called, the loop has finished and i = 9.
# All closures share the same variable i in the enclosing scope.

# Fix 1: default argument captures the value at definition time
funcs = []
for i in range(10):
    funcs.append(lambda i=i: i)  # default arg evaluated at definition
print([f() for f in funcs])  # [0, 1, 2, ..., 9] ✓

# Fix 2: factory function creates a new scope for each i
def make_func(val):
    return lambda: val
funcs = [make_func(i) for i in range(10)]
print([f() for f in funcs])  # [0, 1, 2, ..., 9] ✓

# Fix 3: functools.partial
from functools import partial
def identity(x): return x
funcs = [partial(identity, i) for i in range(10)]
```

This matters because it shows up in decorators, callbacks, and event handlers — anywhere you create functions in a loop. The fix with default arguments (`lambda i=i`) is idiomatic but the mechanism is what you need to understand: closures capture variables by name, not by value.

### `nonlocal` and `global` — when assignment changes everything

```python
# Without nonlocal — assignment creates a new local variable
def outer():
    count = 0
    def inner():
        count += 1  # UnboundLocalError — Python sees assignment, treats count as local
    inner()

# With nonlocal — assignment modifies the enclosing scope's variable
def outer():
    count = 0
    def inner():
        nonlocal count
        count += 1  # Now modifies outer's count
    inner()
    print(count)  # 1 ✓

# global — modifies module-level variable
total = 0
def increment():
    global total
    total += 1

# The rule: reading a variable walks LEGB (Local → Enclosing → Global → Builtins).
# Assigning to a variable WITHOUT declaration creates/binds in Local.
# nonlocal says "assign to the nearest enclosing scope that has this name."
# global says "assign to the module-level scope."
```

The `nonlocal` keyword was added in Python 3 specifically because closures that need mutable state were awkward without it. Before `nonlocal`, you had to use a mutable container like `count = [0]` and mutate `count[0]`. `nonlocal` is cleaner but the underlying principle is the same: you need a way to signal that an assignment isn't creating a new local binding.

### `*args` and `**kwargs` — unpacking mechanics

```python
def func(a, b, *args, **kwargs):
    print(f"a={a}, b={b}")
    print(f"args={args}")        # tuple of extra positional args
    print(f"kwargs={kwargs}")    # dict of extra keyword args

func(1, 2, 3, 4, 5, x=6, y=7)
# a=1, b=2, args=(3, 4, 5), kwargs={'x': 6, 'y': 7}

# Unpacking at call site
nums = [1, 2, 3]
opts = {'timeout': 30, 'retries': 3}
request(*nums, **opts)  # equivalent to request(1, 2, 3, timeout=30, retries=3)

# Python 3.5+ allows multiple unpacking
combined = [*nums, *nums]  # [1, 2, 3, 1, 2, 3]
merged = {*opts, **{'extra': True}}  # {'timeout': 30, 'retries': 3, 'extra': True}

# Keyword-only parameters — everything after * must be passed by name
def api_call(endpoint, *, timeout=30, retries=3):
    pass
api_call("/users")           # OK — defaults
api_call("/users", 60)       # TypeError — timeout is keyword-only
api_call("/users", timeout=60)  # OK
```

Keyword-only parameters are a design tool: they force callers to be explicit about certain arguments, improving readability and preventing accidental positional argument errors. This is especially useful for functions with many optional parameters.

### `functools.wraps` — preserving metadata in decorators

```python
from functools import wraps

def my_decorator(func):
    def wrapper(*args, **kwargs):
        """Wrapper's docstring"""
        print("before")
        return func(*args, **kwargs)
    return wrapper

@my_decorator
def greet(name):
    """Original docstring"""
    return f"Hello, {name}"

print(greet.__name__)   # "wrapper" — not "greet"!
print(greet.__doc__)    # "Wrapper's docstring" — lost original

# Without wraps, the decorated function's metadata is replaced by the wrapper's.
# This breaks introspection, debugging, and tools that rely on __name__/__doc__.

# Fix:
def my_decorator(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        """Wrapper's docstring"""
        print("before")
        return func(*args, **kwargs)
    return wrapper

# Now greet.__name__ == "greet", greet.__doc__ == "Original docstring"
# And functools.update_wrapper also copies __module__, __qualname__, __annotations__,
# and __dict__ — everything needed for the decorated function to look like the original.
```

This is the most common mistake in decorator writing. Without `wraps`, any tool that inspects the function (logging, debugging, testing frameworks, even `help()`) sees the wrapper, not the original. In a codebase with many decorators, this makes introspection essentially useless.

## Common mistakes / gotchas

- **Late binding in closures** — loop variables captured by lambdas all point to the last value. Use default arguments or a factory function to capture the value at definition time.
- **Mutating default arguments** — covered in [[redemption/python/basics]], but it's fundamentally a scope/binding issue: defaults are evaluated once at function definition.
- **Forgetting `nonlocal` in nested functions** — assignment creates a local, causing `UnboundLocalError` when you try to read before assigning. The error message is misleading — the variable *does* exist, just not locally yet.
- **`global` inside a function that also reads before writing** — if you read a global before assigning to it (without `global` declaration), Python treats it as a global read. If you assign anywhere in the function, Python treats all references as local, including reads before the assignment — causing `UnboundLocalError`.
- **`*args` captures as tuple, `**kwargs` as dict** — they're not magical. They're just convenient syntax for packing/unpacking. You can iterate over them, pass them to other functions, etc.
- **Functions are objects with attributes** — you can set `func.counter = 0` and increment it inside the function. This is how stateful decorators work without `nonlocal`.
- **`lambda` is expression-only** — it can only contain a single expression, not statements. For anything more complex, use a `def`. Also, `lambda` has no `__name__` beyond `<lambda>`, which makes debugging harder.

## Practice

> [!question]- Q1. What does this print? Explain the closure behavior.
```python
def make_adder(x):
    def adder(y):
        return x + y
    return adder

add5 = make_adder(5)
add10 = make_adder(10)
print(add5(3))
print(add10(3))
```
**Answer:** Prints `8` then `13`. Each call to `make_adder` creates a new closure — the inner `adder` function captures the specific value of `x` from that invocation's scope. `add5`'s closure has `x=5`, `add10`'s has `x=10`. They don't interfere because each `make_adder` call creates a new scope frame.

> [!question]- Q2. This decorator breaks when used on a function that's called recursively. Why, and how do you fix it?
```python
def count_calls(func):
    def wrapper(*args, **kwargs):
        wrapper.calls = getattr(wrapper, 'calls', 0) + 1
        return func(*args, **kwargs)
    return wrapper

@count_calls
def factorial(n):
    if n <= 1:
        return 1
    return n * factorial(n - 1)

print(factorial(5))
print(factorial.calls)
```
**Answer:** The recursive calls go to `factorial` — which is now the `wrapper` function. So every recursive call increments the counter. For `factorial(5)`, `calls` will be 5 (one for each call including the base case). This is actually correct behavior if you want to count total invocations. But if you wanted to count only top-level calls, you'd need to track depth or use a different mechanism. The fix for top-level-only counting: check if the current call is already inside the wrapper using a `threading.local()` flag or a depth counter. The deeper issue: decorators on recursive functions redirect all calls through the wrapper, which may or may not be what you want.

> [!question]- Q3. Write a `memoize` decorator that caches function results based on arguments. Handle both positional and keyword arguments. What are the limitations of your approach?
**Answer:**
```python
from functools import wraps
import hashlib

def memoize(func):
    cache = {}
    @wraps(func)
    def wrapper(*args, **kwargs):
        # Create a hashable key from args and sorted kwargs
        key = (args, tuple(sorted(kwargs.items())))
        if key not in cache:
            cache[key] = func(*args, **kwargs)
        return cache[key]
    return wrapper
```
Limitations: (1) All arguments must be hashable — lists, dicts, sets can't be arguments. (2) Cache grows unbounded — needs an LRU eviction policy for long-running functions. (3) Doesn't handle mutable default arguments correctly if the function mutates its args. (4) Thread-unsafe — concurrent calls may compute the same result twice. The standard library `functools.lru_cache` solves all of these: it handles hashable-only args (raises TypeError otherwise), has maxsize for LRU, and is thread-safe.

> [!question]- Q4. Explain the difference between these two functions and why one is thread-safe and the other isn't:
```python
def counter_v1():
    count = 0
    def increment():
        nonlocal count
        count += 1
    return increment

def counter_v2():
    count = [0]
    def increment():
        count[0] += 1
    return increment
```
**Answer:** Both have the same thread-safety properties: neither is thread-safe. `count += 1` and `count[0] += 1` are both read-modify-write sequences that can interleave between threads. The `nonlocal` version and the list-capture version are semantically equivalent in terms of thread safety — both suffer from the race condition. The misconception is that using a list makes it "atomic" because it's a mutation — it's not. Python's GIL makes single bytecode operations atomic, but `+=` compiles to multiple bytecodes (LOAD, ADD, STORE), so it can be interrupted. To make it thread-safe, you'd need a `threading.Lock`. The point: the GIL doesn't make all operations thread-safe — only single bytecode operations. `+=` is not a single bytecode operation.

> [!question]- Q5. What does `inspect.signature` reveal about a function decorated without `@wraps`, and why does this matter for API documentation tools?
**Answer:** Without `@wraps`, `inspect.signature(decorated_func)` returns the signature of the `wrapper` function — typically `(*args, **kwargs)` — not the original function's signature. API documentation tools (like Sphinx, FastAPI's auto-docs, and OpenAPI generators) use `inspect.signature` to discover parameters. If the wrapper hides the real signature, the documentation shows `(*args, **kwargs)` with no useful parameter info. This breaks auto-generated docs, IDE autocomplete, and type checkers that rely on signature introspection. `@wraps` copies `__wrapped__` attribute which `inspect.signature` follows, restoring the original signature.

## Related
[[redemption/python/basics]]
[[decorators]]
[[generators-and-iterators]]
[[context-managers]]
[[gil-and-threading]]

#status/new