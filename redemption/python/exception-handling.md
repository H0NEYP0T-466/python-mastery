# Exception Handling

## What it is
Python's exception mechanism is a control-flow tool — not just for errors, but for signaling exceptional conditions that break the normal execution path. The hierarchy (`BaseException` → `Exception` → specific exceptions), the `try/except/else/finally` clauses, custom exception types, and exception chaining (`raise from`) form a system that, when used correctly, makes code more robust and easier to reason about. When used poorly, it leads to silent failures, swallowed errors, and exception-based control flow that's harder to read than explicit conditionals.

## Why it matters
AI-generated code tends toward bare `except:` or `except Exception:` everywhere — catching more than intended and hiding bugs. In production, a bare `except` catches `KeyboardInterrupt` and `SystemExit`, making your process unkillable. In interviews, exception handling questions test whether you understand exception chaining, the difference between `else` and `finally`, and when to catch vs. when to let propagate. The "ask forgiveness, not permission" (EAFP) philosophy is Python-specific — and knowing when to use it vs. "look before you leap" (LBYL) is a mark of Python maturity.

## Core example

### The full try/except/else/finally structure

```python
try:
    # Risky code — may raise
    result = compute(x)
except ValueError as e:
    # Handles ONLY ValueError — specific, targeted
    print(f"Bad input: {e}")
    result = default_value
except (TypeError, KeyError) as e:
    # Multiple exception types in one handler
    print(f"Type/key error: {e}")
    result = None
else:
    # Runs ONLY if NO exception was raised in the try block
    # This is NOT "after try" — it's "after successful try"
    # Use for code that should run only when the try succeeded
    print(f"Computation succeeded: {result}")
finally:
    # ALWAYS runs — whether exception occurred or not
    # Use for cleanup: closing files, releasing locks, etc.
    # Even if a return statement is in try/except/else, finally runs
    cleanup()

# The order matters: except clauses are checked top to bottom.
# More specific exceptions must come before more general ones.
# If you put except Exception before except ValueError, the ValueError
# handler is unreachable — and Python doesn't warn about this.
```

The `else` clause is the most misunderstood part. It runs only when the `try` block completes without raising — but before `finally`. It's useful for code that should run only on success, and that you don't want inside the `try` block (because if it raises, you don't want it caught by the same `except`). A common pattern: the `try` does the risky operation, `else` processes the result, and `finally` cleans up.

### Bare `except` vs `except Exception` — the critical difference

```python
# DANGEROUS — catches EVERYTHING including SystemExit and KeyboardInterrupt
try:
    do_something()
except:
    print("Something went wrong")  # Can't even Ctrl-C out of this!

# Better — catches all regular exceptions but lets SystemExit/KeyboardInterrupt through
try:
    do_something()
except Exception as e:
    print(f"Error: {e}")

# Best — catch specific exceptions you can actually handle
try:
    do_something()
except FileNotFoundError:
    use_default_config()
except PermissionError:
    log_permission_denied()
except ValueError as e:
    handle_bad_input(e)
```

`BaseException` is the root of the exception hierarchy. `SystemExit`, `KeyboardInterrupt`, and `GeneratorExit` inherit from `BaseException` directly, NOT from `Exception`. This is intentional — they're control signals, not errors. A bare `except:` catches `BaseException`, which means it catches the user pressing Ctrl-C and `sys.exit()` calls. This is almost always wrong.

### Exception chaining — `raise from`

```python
def load_config(path):
    try:
        with open(path) as f:
            return parse(f.read())
    except FileNotFoundError as e:
        # Re-raise a higher-level exception, preserving the original
        raise ConfigError(f"Config not found: {path}") from e

# Without 'from', the original exception is lost:
# except FileNotFoundError:
#     raise ConfigError(...)  # The __cause__ is None — original context lost

# With 'from', the traceback shows both exceptions:
# ConfigError: Config not found: /etc/app/config.yaml
# The above exception was the direct cause of the following exception:
# FileNotFoundError: [Errno 2] No such file or directory: '/etc/app/config.yaml'

# 'raise from None' suppresses the chained exception entirely:
# Used when you want to replace one exception with another without
# showing the internal details:
try:
    parse(data)
except ValueError:
    raise ConfigError("Invalid config format") from None
```

Exception chaining is crucial for building clean API boundaries. Your library shouldn't leak internal implementation exceptions (like a `json.JSONDecodeError` from deep inside your config loader). You convert them to your domain exception (`ConfigError`) while preserving the original via `raise from`. This gives users a clean error interface while keeping the full traceback available for debugging.

### Custom exception types — building a hierarchy

```python
class AppError(Exception):
    """Base exception for the application — catch this to handle all app errors"""
    pass

class ValidationError(AppError):
    """Raised when user input fails validation"""
    def __init__(self, field, message):
        self.field = field
        self.message = message
        super().__init__(f"{field}: {message}")

class DatabaseError(AppError):
    """Raised when database operations fail"""
    def __init__(self, query, original_error):
        self.query = query
        self.original_error = original_error
        super().__init__(f"Query failed: {query}")

class AuthError(AppError):
    """Raised when authentication fails"""
    pass

# Usage:
# raise ValidationError("email", "must be a valid email address")
# catch with: except AppError: (catches all) or except ValidationError: (specific)

# Why custom exceptions:
# 1. Specificity — callers can catch exactly what they can handle
# 2. Context — you can attach custom fields (field name, query, error code)
# 3. Abstraction — hide internal exceptions behind your domain exceptions
# 4. Documentation — the exception types document what can go wrong
```

### EAFP vs LBYL — Python's philosophy

```python
# LBYL — Look Before You Leap (check first, then act)
if key in d:
    value = d[key]
else:
    value = default

# EAFP — Easier to Ask for Forgiveness than Permission (act, handle failure)
try:
    value = d[key]
except KeyError:
    value = default

# Python prefers EAFP because:
# 1. It's atomic — no race condition between the check and the access
#    (in multi-threaded code, the key could be deleted between 'in' check and access)
# 2. It's faster in the common case — no double lookup
# 3. It's more readable — the happy path is the main line of code

# But LBYL is appropriate when:
# The check is significantly cheaper than the exception (e.g., checking
# a flag before an expensive operation)
# You need to validate multiple conditions before proceeding
# You're building a pre-flight check (e.g., validating all inputs before
# starting a long operation)

# The built-in dict.get() method is the cleanest LBYL pattern:
value = d.get(key, default)
```

### Exception groups (Python 3.11+) — handling multiple exceptions

```python
# Python 3.11 introduced ExceptionGroup and except* for concurrent code
# where multiple exceptions can occur simultaneously

errors = []
try:
    task1()
except Exception as e:
    errors.append(e)

try:
    task2()
except Exception as e:
    errors.append(e)

if errors:
    raise ExceptionGroup("Multiple tasks failed", errors)

# Handling with except*:
try:
    raise ExceptionGroup("errors", [ValueError("a"), TypeError("b")])
except* ValueError as eg:
    # eg is an ExceptionGroup containing only ValueErrors
    print(f"ValueErrors: {eg.exceptions}")
except* TypeError as eg:
    print(f"TypeErrors: {eg.exceptions}")

# This is primarily relevant for asyncio and concurrent.futures where
# multiple tasks can fail independently. For sequential code, traditional
# try/except is sufficient.
```

## Common mistakes / gotchas

- **Bare `except:`** — catches `KeyboardInterrupt`, `SystemExit`, and `GeneratorExit`, making your process unkillable and hiding critical errors. Always use `except Exception:` or a specific exception type.
- **Catching too broadly** — `except Exception:` catches everything that's not a system exit. This is better than bare `except` but still often too broad. Catch what you can handle and let the rest propagate.
- **Swallowing exceptions** — `except: pass` or `except Exception: pass` silently discards errors. This is the #1 cause of "the script runs but produces no output" bugs. At minimum, log the exception.
- **Exception order** — putting a general exception handler before a specific one makes the specific handler unreachable. Python doesn't warn about this (it's not a syntax error). Always order from most specific to most general.
- **Using exceptions for normal control flow** — `try/except` is for exceptional conditions, not for "item not found in a list that's frequently empty." If a condition is expected, use an `if` check. Exceptions are expensive — raising and catching is ~100x slower than a simple check.
- **Not cleaning up in `finally`** — if you acquire a resource in `try` and release it in `except`, you leak the resource when no exception occurs. Use `finally` (or better, a context manager) for guaranteed cleanup.
- **Raising without preserving context** — `raise SomeError("msg")` inside an `except` block loses the original exception. Use `raise SomeError("msg") from original` to preserve the chain. Use `raise from None` only when you intentionally want to hide the internal details.
- **Exceptions in `__del__`** — raising an exception in `__del__` (finalizer) is dangerous because `__del__` is called during garbage collection, and exceptions there are ignored or cause undefined behavior. Use context managers or explicit cleanup instead.

## Practice

> [!question]- Q1. What does this code print? Explain the flow.
```python
def test():
    try:
        print("A")
        raise ValueError("oops")
        print("B")
    except ValueError:
        print("C")
        raise
        print("D")
    finally:
        print("E")
    print("F")

test()
```
**Answer:** Prints "A", "C", "E", then re-raises the ValueError. "B" is never printed because the exception is raised before it. "D" is never printed because `raise` in the except block exits immediately. "E" is printed because `finally` always runs — even when re-raising. "F" is never printed because the exception propagates out of the function. The `raise` without arguments in an except block re-raises the current exception, preserving the original traceback.

> [!question]- Q2. You have a function that reads a config file. If the file doesn't exist, create it with defaults. If it exists but is malformed, raise a custom `ConfigError`. Implement this with proper exception handling and explain your choices.
**Answer:**
```python
import json
import os

class ConfigError(Exception):
    pass

def load_config(path):
    defaults = {"theme": "dark", "language": "en", "volume": 0.5}
    
    if not os.path.exists(path):
        # LBYL is appropriate here — existence check is cheap and
        # creating the file is the expected behavior for first run
        with open(path, "w") as f:
            json.dump(defaults, f)
        return defaults.copy()
    
    try:
        with open(path) as f:
            config = json.load(f)
        # Merge with defaults for missing keys
        return {**defaults, **config}
    except json.JSONDecodeError as e:
        # EAFP — parsing may fail; we handle it specifically
        raise ConfigError(f"Config file is corrupted: {e}") from e
    except PermissionError as e:
        raise ConfigError(f"Cannot read config file (permission denied): {path}") from e
```
The LBYL check for file existence is appropriate because creating a default config on first run is expected behavior, not an exception. The JSON parsing uses EAFP — we try to parse and handle the specific failure mode. The `raise from` preserves the original `JSONDecodeError` traceback for debugging while presenting a cleaner `ConfigError` to the caller.

> [!question]- Q3. Write a decorator `retry(exc_types, max_attempts, backoff=1)` that retries a function when it raises specific exceptions. Include exponential backoff. What edge cases must you handle?
**Answer:**
```python
import time
import functools
from functools import wraps

def retry(exc_types, max_attempts=3, backoff=1):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exc_types as e:
                    last_error = e
                    if attempt >= max_attempts:
                        break
                    wait = backoff * (2 ** (attempt - 1))  # Exponential backoff
                    print(f"Attempt {attempt}/{max_attempts} failed: {e}. Retrying in {wait}s...")
                    time.sleep(wait)
            raise last_error
        return wrapper
    return decorator

@retry((ConnectionError, TimeoutError), max_attempts=4, backoff=2)
def api_call():
    ...
```
Edge cases: (1) `exc_types` must be a tuple of exception classes — if a single class is passed, it works because `except Class` is valid, but `except (Class,)` is the tuple form. (2) If the function is not idempotent, retrying may cause side effects — the decorator can't know this. (3) Exponential backoff without a cap can lead to very long waits — add a `max_backoff` parameter. (4) Thread safety — if the decorator maintains shared state (like a retry counter across calls), it needs locking. (5) The function might succeed on a later attempt but the caller may have timed out — the decorator doesn't know about caller-side timeouts.

> [!question]- Q4. Explain the difference between `raise`, `raise e`, and `raise from e` inside an except block catching exception `e`.
**Answer:** `raise` (with no arguments) re-raises the currently handled exception, preserving the original traceback and exception chain. This is the correct way to "handle then re-raise." `raise e` raises the exception object `e` but creates a NEW traceback starting from this point — the original traceback is lost, and the exception appears to originate from the `raise e` line. `raise from e` sets `e` as the `__cause__` of the current exception, creating an explicit chain — the traceback shows both the original and the new exception with "The above exception was the direct cause of the following exception." The practical rule: use bare `raise` to re-raise the caught exception. Use `raise from` when converting to a different exception type. Avoid `raise e` inside an except block — it loses the original context.

> [!question]- Q5. Why is catching `Exception` different from catching `BaseException`? Give three examples of exceptions that are caught by one but not the other, and explain why the distinction matters.
**Answer:** `BaseException` is the root of the exception hierarchy. `Exception` inherits from `BaseException`. Three exceptions that are `BaseException` but NOT `Exception`: (1) `SystemExit` — raised by `sys.exit()`. If you catch this, you prevent the program from exiting when explicitly told to. (2) `KeyboardInterrupt` — raised when the user presses Ctrl-C. If you catch this, you make the program unkillable via Ctrl-C. (3) `GeneratorExit` — raised when a generator is closed. If you catch this inside a generator's `finally` block, you can prevent proper cleanup. The distinction matters because these are control signals, not errors. Catching them accidentally (via bare `except:`) leads to programs that can't be stopped, can't exit cleanly, and hang during shutdown. The rule: catch `Exception` (or specific subclasses) unless you have a very specific reason to catch `BaseException` (e.g., a top-level error handler that logs everything before re-raising).

## Related
[[redemption/python/basics]]
[[context-managers]]
[[oop-and-dunder-methods]]
[[logging]]

#status/new