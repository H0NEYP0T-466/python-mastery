# Basics

## What it is
This isn't a syntax tutorial. You know how to write a `for` loop. This is the collection of behaviors that AI-generated code glosses over — the subtle, non-obvious corners of Python's core mechanics that surface in code review, debugging sessions, and interviews. Mutable defaults, identity vs equality, interning, truthy/falsy edge cases, chained comparisons, and `for...else`. Each one is a place where "it works" and "it's correct" diverge.

## Why it matters
These aren't trivia. A mutable default argument silently shared across function calls is the kind of bug that surfaces in production after weeks of "fine" behavior. Using `is` for equality checks on integers works until it doesn't — because small-int caching has a boundary. AI-generated code exploits these gaps because it patterns-matches on common cases, not edge cases. Internalizing them means you can read code and immediately spot whether a pattern is safe or a time bomb.

## Core example

### Mutable default arguments — the classic trap

```python
def add_item(item, container=[]):
    container.append(item)
    return container

print(add_item(1))        # [1]
print(add_item(2))        # [1, 2]   ← not [2]!
print(add_item(3))        # [1, 2, 3]
```

The default list is created **once**, at function definition time, and reused on every call. The object persists across invocations. This is not a bug in Python — it's a consequence of how default arguments are evaluated. The fix:

```python
def add_item(item, container=None):
    if container is None:
        container = []
    container.append(item)
    return container
```

The `None` pattern forces a fresh object per call. This matters because the buggy version works correctly the first time — making it invisible to casual testing.

### `is` vs `==` and small-integer caching

```python
a = 256
b = 256
print(a is b)   # True  — cached

a = 257
b = 257
print(a is b)   # False — not cached (in CPython, in interactive mode)

# But in a script file, CPython may optimize both to the same object
# because the compiler interns constants in the same code block.
```

`==` compares values via `__eq__`. `is` compares identity — whether two names point to the same object. CPython caches integers in the range `[-5, 256]` as a performance optimization because these are frequently reused. Outside that range, each literal creates a new object — unless the compiler reuses it within the same code block. **Never use `is` to compare values.** Only use it for singletons: `is None`, `is True`, `is False`.

```python
# Correct
if value is None:
    ...

# Wrong
if x is 5:
    ...
```

### Truthy/falsy edge cases

```python
# These are falsy: False, 0, 0.0, '', [], {}, set(), None, range(0)

# The subtle ones:
print(bool([None]))   # True  — a list with one element is truthy, even if that element is falsy
print(bool([0]))      # True  — same reasoning
print(bool([False]))  # True  — the list is non-empty

# Empty collections are falsy, but the presence of a falsy element
# does NOT make the collection falsy.

# Strings: empty string is falsy, but "0" and "False" are truthy
print(bool("0"))      # True
print(bool("False"))  # True

# Numpy arrays and pandas Series raise ValueError on bool()
# because their truthiness is ambiguous — use .any() / .all() explicitly
```

The practical rule: test `if container:` for emptiness, but if you need to check whether a list *contains* a falsy value, you must be explicit — `if any(x is False for x in items)` — because `if items:` won't tell you what's inside.

### Chained comparisons

```python
x = 5
print(1 < x < 10)     # True
print(1 < x < 3)      # False
print(1 < 3 > 2)      # True

# This is NOT parsed as (1 < x) < 3  →  True < 3 → error
# It's parsed as: (1 < x) and (x < 10)
# Each comparison shares the middle operand.

# This also works with mixed operators:
print(1 <= x <= 5)    # True
print(5 > x >= 1)     # True
print(1 < x > 3)      # True  (x > 1 AND x > 3)

# But be careful — the middle expression is evaluated only ONCE:
def get_x():
    print("evaluated")
    return 5

_ = 1 < get_x() < 10  # "evaluated" printed once, not twice
```

This is Python-specific. In C, `1 < x < 10` compiles to `(1 < x) < 10` which is always `1` (since boolean results are 0 or 1, and both are `< 10`). Python's behavior is mathematically correct and matches mathematical notation — which is exactly why it surprises people coming from other languages.

### `for...else` — the construct nobody uses but everyone should

```python
def find_prime(n):
    for i in range(2, int(n**0.5) + 1):
        if n % i == 0:
            print(f"{n} is divisible by {i}")
            break
    else:
        # This runs ONLY if the loop completed without hitting `break`
        print(f"{n} is prime")

find_prime(17)   # "17 is prime"
find_prime(15)   # "15 is divisible by 3" — no else
```

The `else` clause on a `for` or `while` loop executes when the loop exhausts its iterable (or condition becomes false) **without encountering `break`**. It does NOT run if the loop body never executes — an empty iterable skips the `else` too, because the loop didn't "complete normally," it just had nothing to do.

The mental model: `for...else` is "search and if-not-found." The `break` means "I found it, stop." The `else` means "I looked through everything and didn't find it." Without `else`, you need a flag variable — `found = False` — which is more verbose and more error-prone.

### String interning

```python
a = "hello"
b = "hello"
print(a is b)   # True — Python interns identical string literals

a = "hello world"
b = "hello world"
print(a is b)   # Usually True, but implementation-dependent

# Strings created at runtime are NOT automatically interned:
a = "hello"
b = "hel" + "lo"   # compile-time concatenation → interned
print(a is b)      # True

c = "".join(["hel", "lo"])  # runtime → not interned
print(a is c)      # May be False

# You can force interning:
import sys
d = sys.intern("hello world")
e = sys.intern("hello world")
print(d is e)      # Always True
```

CPython interns string literals that look like identifiers (alphanumeric + underscores) because they're commonly used as variable names, dictionary keys, and attribute names — where identity comparison is far faster than character-by-character equality. Runtime strings are not interned because the cost of interning (hashing + table lookup) isn't worth it for strings that may be used once. Use `sys.intern()` when you have a known set of repeated strings (e.g., token types in a parser, enum-like string values) and want identity-level comparison speed.

## Common mistakes / gotchas

- **Mutable defaults persist across calls** — the default object is created once at definition time. Use `None` and instantiate inside the function.
- **`is` for value comparison works only by accident** — small-int caching and string interning make `is 5` or `is "hello"` appear to work, but it's undefined behavior outside those specific cases.
- **`[None]` is truthy** — a non-empty container is truthy regardless of its contents. `if my_list:` checks emptiness, not whether contents are meaningful.
- **`for...else` is not "loop then else"** — the `else` runs only if no `break` occurred. If you think of it as "if-not-found," it becomes readable.
- **Chained comparisons are not left-to-right boolean evaluation** — `1 < x < 10` is `1 < x and x < 10`, with `x` evaluated once. In C/C++/Java, the same syntax produces different results.
- **Modifying a list while iterating over it** — `for x in lst: if cond: lst.remove(x)` skips elements because the iterator index doesn't adjust. Iterate over a copy (`for x in lst[:]`) or build a new list.
- **`==` can be overridden, `is` cannot** — a class can make `==` return anything (including `True` for unequal objects), but `is` always checks object identity.
- **Mutable objects as dictionary keys** — lists and dicts are unhashable and cannot be keys. Tuples are hashable only if all their contents are hashable. `([1],)` is unhashable.

## Practice

> [!question]- Q1. What does this print, and why?
```python
def append_to(val, items=[]):
    items.append(val)
    return items

print(append_to(1))
print(append_to(2))
print(append_to(3, []))
```
**Answer:** Prints `[1]`, then `[1, 2]`, then `[3]`. The first two calls share the same default list object created at definition time. The third call passes an explicit new list, so it returns `[3]` independently. The bug is that the shared list accumulates across calls — a classic mutable default trap.

> [!question]- Q2. Predict the output and explain each line:
```python
a = [1, 2, 3]
b = [1, 2, 3]
c = a
print(a == b)
print(a is b)
print(a is c)
print(a is [1, 2, 3])
```
**Answer:** `True` (values equal via `__eq__`), `False` (different objects in memory — each `[...]` literal creates a new list), `True` (`c` is an alias for `a`, same object), `False` (the literal `[1, 2, 3]` on that line creates a new object distinct from `a`). Only `is` with the same variable reference returns `True`.

> [!question]- Q3. Write a function `find_all_indices(lst, target)` that returns all indices where `target` appears in `lst`, using `for...else` appropriately. Then explain why `else` is the right choice here instead of a flag variable.
**Answer:**
```python
def find_all_indices(lst, target):
    found = []
    for i, val in enumerate(lst):
        if val == target:
            found.append(i)
    else:
        if not found:
            return [-1]  # target not found anywhere
    return found
```
Actually — `for...else` is a poor fit here because we're not breaking on first match; we're collecting all matches. The `else` runs when the loop completes normally (no break), which is always the case here. A cleaner version without `else`:
```python
def find_all_indices(lst, target):
    found = [i for i, v in enumerate(lst) if v == target]
    return found if found else [-1]
```
The point: `for...else` is only the right tool when you `break` on a condition and want to handle the "not found" case. For collecting all matches, a comprehension or a flag is clearer. Recognizing when NOT to use a construct is as important as knowing how to use it.

> [!question]- Q4. What does this print? Explain the interning behavior.
```python
import sys
a = "hello_world"
b = "hello_world"
c = "hello world"
d = "hello world"
print(a is b)
print(c is d)
print(sys.intern(c) is sys.intern(d))
```
**Answer:** `True` (identifier-looking strings are automatically interned), likely `True` but implementation-dependent (strings with spaces may or may not be interned by the compiler — CPython often interns all identical string literals in the same code block, but this is not guaranteed), `True` (explicit `sys.intern()` guarantees the same interned object for equal strings).

> [!question]- Q5. Explain why this code is buggy and produces inconsistent results:
```python
def process(data):
    result = {}
    for item in data:
        if item.type == "A":
            result["type_a"] = item.value
        elif item.type == "B":
            result["type_b"] = item.value
    else:
        result["processed"] = True
    return result
```
**Answer:** The `else` clause here is meaningless — it always runs because the loop never `breaks`. The `else` on a loop only has semantic value when there's a `break` path. Here, `result["processed"] = True` will always be set regardless of whether the loop body even executed (empty `data`). The developer likely confused `for...else` with "after the loop" semantics. The fix is to move `result["processed"] = True` outside the loop entirely, without `else`, making the intent explicit.

## Related
[[functions-and-scope]]
[[oop-and-dunder-methods]]
[[memory-management-and-gc]]
[[gil-and-threading]]

#status/new