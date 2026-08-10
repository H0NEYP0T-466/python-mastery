# Generators and Iterators

## What it is
Python's iterator protocol — `__iter__` and `__next__` — is the mechanism behind `for` loops, comprehensions, and anything that consumes sequences. Generators (`yield` and `yield from`) are a concise way to implement iterators without writing a class. But the real power — and the subtle bugs — come from understanding how generators manage state, how `yield from` delegates to sub-generators, how generator expressions differ from list comprehensions in memory behavior, and how exhaustion works (once a generator is consumed, it's done). This file covers the protocol, the mechanics, and the patterns that turn O(n) memory into O(1).

## Why it matters
Generators are the foundation of lazy evaluation in Python — they let you process streams of data that don't fit in memory, chain transformations without intermediate allocations, and express infinite sequences. In data processing (which you do constantly — DINOv2 training, GPT-2 data pipelines), the difference between a generator pipeline and a list-based pipeline is the difference between running in 2GB of RAM and running in 20GB. Interview questions about generators test whether you understand the protocol deeply enough to implement custom iterators, not just use `yield`. And the exhaustion bug — trying to reuse a generator — is one of the most common "it worked the first time but not the second" surprises.

## Core example

### The iterator protocol — what `for` loop actually does

```python
# A for loop:
for item in iterable:
    print(item)

# Is equivalent to:
iterator = iter(iterable)  # calls iterable.__iter__()
while True:
    try:
        item = next(iterator)  # calls iterator.__next__()
        print(item)
    except StopIteration:
        break

# An iterator is any object with __iter__ (returns self) and __next__
# (returns next value or raises StopIteration). An iterable is any object
# with __iter__ that returns an iterator. Lists are iterable but not
# iterators — their __iter__ returns a new list_iterator each time.
# Generators are both — they are their own iterators.
```

The key distinction: an **iterable** can be iterated over multiple times (each call to `iter()` gives a fresh iterator). An **iterator** can only be iterated once — once `StopIteration` is raised, it's exhausted. This is why `for item in my_list:` works every time, but `for item in my_generator:` only works the first time.

### Basic generator — state is preserved between yields

```python
def count_up_to(n):
    i = 1
    while i <= n:
        yield i  # pauses here, returns i, preserves local state
        i += 1   # resumes here on next() call

for num in count_up_to(3):
    print(num)  # 1, 2, 3

# The generator function doesn't run when you call it.
# count_up_to(3) returns a generator object — nothing executes yet.
# The function body runs only when you call next() on the generator,
# and it runs until it hits yield. Then it pauses, preserving all local
# variables. On the next next(), it resumes after the yield.

# This is fundamentally different from a function that returns a list:
def count_up_to_list(n):
    return list(range(1, n + 1))  # builds entire list in memory

# For n=3, no difference. For n=10_000_000, the generator uses O(1) memory
# while the list uses O(n) memory.
```

### Generator expressions vs list comprehensions — memory matters

```python
# List comprehension — builds the entire list in memory
squares_list = [x*x for x in range(1000000)]  # ~8MB for the list

# Generator expression — produces values on demand
squares_gen = (x*x for x in range(1000000))   # ~120 bytes for the generator object

# The generator doesn't compute any squares yet.
# Each value is computed when you iterate.

# When to use which:
# - Use list comprehension when you need the full list (random access,
#   multiple passes, len(), indexing)
# - Use generator expression when you're piping into sum(), max(),
#   any(), or a single-pass consumer

# sum(x*x for x in range(1000000)) — generator, O(1) memory
# sum([x*x for x in range(1000000)]) — list, O(n) memory, same result

# But: if you need to consume twice, a generator won't work:
gen = (x for x in range(5))
print(list(gen))  # [0, 1, 2, 3, 4]
print(list(gen))  # [] — exhausted!

# Solution: either recreate the generator, or use a list if you need
# multiple passes. Or use itertools.tee to split into independent iterators
# (but this buffers internally, losing the memory benefit).
```

### `yield from` — delegating to a sub-generator

```python
def flatten(nested):
    """Flatten a nested list of arbitrary depth"""
    for item in nested:
        if isinstance(item, list):
            yield from flatten(item)  # delegate to sub-generator
        else:
            yield item

nested = [1, [2, 3, [4, 5]], 6]
print(list(flatten(nested)))  # [1, 2, 3, 4, 5, 6]

# yield from does more than just iterate — it:
# 1. Yields all values from the sub-generator
# 2. Forwards .send() calls to the sub-generator
# 3. Forwards .throw() and .close() to the sub-generator
# 4. Returns the sub-generator's return value (if it uses return value)

# This makes yield from the correct way to compose generators,
# not just a syntax shortcut.

# Example with return value:
def sub_gen():
    yield 1
    yield 2
    return "sub done"

def main_gen():
    result = yield from sub_gen()
    print(f"Sub-generator returned: {result}")
    yield "main done"

print(list(main_gen()))  # Sub-generator returned: sub done, then [1, 2, 'main done']
```

### Sending values into generators — two-way communication

```python
def accumulator():
    total = 0
    while True:
        value = yield total  # receives a value via .send()
        if value is None:
            break
        total += value

acc = accumulator()
next(acc)        # Prime the generator — must call next() before send()
print(acc.send(10))   # 10
print(acc.send(20))   # 30
print(acc.send(5))    # 35
acc.send(None)   # Stop the generator

# The pattern: yield can both produce AND consume.
# When you use yield on the right side of an assignment, it receives
# a value from .send(). This is how generators become coroutines.

# Important: you MUST prime the generator with next() before send().
# Otherwise, you get TypeError: can't send non-None value to a
# just-started generator — because the generator hasn't reached the
# yield yet, so there's nowhere to send the value to.
```

### Generators as coroutines — the precursor to async/await

```python
# Before async/await, Python used generators as coroutines.
# The pattern: a generator yields control, and a scheduler resumes it.

def simple_coroutine():
    print("Started")
    x = yield
    print(f"Received: {x}")

coro = simple_coroutine()
next(coro)       # Prime — runs to first yield
coro.send(42)    # "Received: 42" then StopIteration

# This is the historical foundation of async/await. In fact, early
# asyncio used @asyncio.coroutine decorators on generators with yield from.
# Modern async/await is built on the same conceptual model but with
# dedicated syntax and an event loop.
```

### Custom iterator class — when a generator isn't enough

```python
class SquareIterator:
    def __init__(self, n):
        self.n = n
        self.i = 0

    def __iter__(self):
        return self

    def __next__(self):
        if self.i >= self.n:
            raise StopIteration
        result = self.i * self.i
        self.i += 1
        return result

# This is equivalent to: (x*x for x in range(n))
# But a class gives you more control: you can add methods, reset state,
# or implement more complex iteration logic that doesn't fit a simple yield.

# Generators are preferred for simple cases because they're more concise
# and automatically handle the iterator protocol. Use a class when you
# need multiple iteration modes, additional methods, or shared state
# across multiple iterators.
```

### `itertools` — the standard library's generator toolkit

```python
import itertools

# chain — concatenate multiple iterables without building a combined list
for item in itertools.chain([1, 2], [3, 4], [5, 6]):
    ...  # 1, 2, 3, 4, 5, 6 — lazy, no intermediate list

# islice — slice an iterator (works on infinite iterators too)
first_5 = itertools.islice(itertools.count(), 5)  # 0, 1, 2, 3, 4

# groupby — group consecutive items by a key (must be sorted first!)
data = sorted(['alice', 'bob', 'anna', 'charlie'], key=lambda x: x[0])
for key, group in itertools.groupby(data, key=lambda x: x[0]):
    print(key, list(group))  # 'a' ['alice', 'anna'], 'b' ['bob'], 'c' ['charlie']

# product — Cartesian product (nested loops as a single iterator)
for x, y in itertools.product([1, 2], ['a', 'b']):
    ...  # (1,a), (1,b), (2,a), (2,b)

# combinations / permutations — combinatorial iterators
list(itertools.combinations([1, 2, 3], 2))  # [(1,2), (1,3), (2,3)]
list(itertools.permutations([1, 2, 3], 2))  # [(1,2), (1,3), (2,1), (2,3), (3,1), (3,2)]

# cycle — infinite iterator cycling through an iterable
# Use with islice to avoid infinite loop:
first_10 = itertools.islice(itertools.cycle('abc'), 10)  # a,b,c,a,b,c,a,b,c,a

# All of these are lazy — they don't allocate intermediate results.
# This is the key to memory-efficient data pipelines.
```

## Common mistakes / gotchas

- **Reusing a generator** — once exhausted, a generator can't be restarted. `list(gen)` then `list(gen)` again gives `[]`. You must recreate the generator or use a list if you need multiple passes.
- **Forgetting to prime a generator before `send()`** — calling `send(value)` on a fresh generator raises `TypeError`. Always call `next()` first to advance to the first `yield`.
- **Generator expressions in function calls** — `sum(x*x for x in range(10))` doesn't need double parentheses. But `func((x for x in range(10)))` does — the outer parens are for the function call, the inner for the generator. Confusing syntax.
- **`yield from` with non-iterables** — `yield from` expects an iterable. If you pass a non-iterable, you get `TypeError` at runtime, not at the `yield from` line but when the generator is consumed.
- **Closing generators** — if a generator holds resources (file handles, network connections) and you don't fully consume it, those resources aren't released until garbage collection. Use `generator.close()` or a context manager (`contextlib.closing`) to ensure cleanup.
- **List comprehension variable leakage in Python 2** — in Python 2, list comprehensions leak their loop variable to the enclosing scope. In Python 3, they have their own scope. This is rarely an issue now but explains old code patterns.
- **Generators are single-threaded by nature** — a generator's state is tied to the thread that created it. You can't safely pass a generator between threads. If you need concurrent consumption, use a `queue.Queue` instead.
- **`StopIteration` inside a generator is caught** — if a generator raises `StopIteration` (other than from `next()` on a sub-iterator), it's converted to `RuntimeError` in Python 3.7+ (PEP 479). This prevents silent bugs where a `StopIteration` inside the generator body prematurely ends iteration.

## Practice

> [!question]- Q1. Write a generator `window(seq, size)` that yields sliding windows of a given size over a sequence. For `window([1,2,3,4,5], 3)`, it should yield `[1,2,3]`, `[2,3,4]`, `[3,4,5]`. What's the memory complexity?
**Answer:**
```python
def window(seq, size):
    from collections import deque
    it = iter(seq)
    win = deque(itertools.islice(it, size), maxlen=size)
    if len(win) == size:
        yield list(win)
    for item in it:
        win.append(item)
        yield list(win)
```
Memory complexity: O(size) — the deque holds at most `size` elements regardless of the input length. The generator itself uses O(1) additional memory. This is optimal for a sliding window — you must keep the current window in memory, but you don't need to buffer the entire input.

> [!question]- Q2. Explain the difference between these two functions and why one is memory-efficient and the other isn't:
```python
def process_large_file_v1(path):
    with open(path) as f:
        lines = f.readlines()
        for line in lines:
            yield process(line)

def process_large_file_v2(path):
    with open(path) as f:
        for line in f:
            yield process(line)
```
**Answer:** `v1` calls `f.readlines()` which loads the entire file into memory as a list of lines — O(n) memory where n is file size. Then it iterates over that list. The generator keyword doesn't help because the file is already fully read. `v2` iterates over the file object directly — file objects are iterators that yield one line at a time, so only one line is in memory at any point — O(1) memory. The `yield` in `v2` genuinely lazy. The key insight: `yield` makes the *function* lazy, but if you eagerly load data inside the function body (like `readlines()`), the laziness is lost.

> [!question]- Q3. What does this code print? Explain the generator state.
```python
def gen():
    print("start")
    yield 1
    print("after 1")
    yield 2
    print("after 2")
    yield 3
    print("done")

g = gen()
print("created generator")
print(next(g))
print(next(g))
print(g.close())
print(next(g))
```
**Answer:** "created generator" (generator created but nothing runs), then "start" then "1" (first next runs to first yield), then "after 1" then "2" (second next resumes after first yield), then `g.close()` closes the generator — raises `GeneratorExit` inside the generator, which is caught and the generator terminates. `close()` returns `None`. The final `next(g)` raises `StopIteration` because the generator is closed and exhausted. The key: `close()` injects `GeneratorExit` at the current yield point, allowing the generator to clean up (via `finally` blocks) before terminating.

> [!question]- Q4. Write a generator that produces Fibonacci numbers infinitely. Then show how to consume only the first N numbers efficiently. What happens if you accidentally convert it to a list?
**Answer:**
```python
def fibonacci():
    a, b = 0, 1
    while True:
        yield a
        a, b = b, a + b

# Consume first N:
first_10 = list(itertools.islice(fibonacci(), 10))  # [0, 1, 1, 2, 3, 5, 8, 13, 21, 34]

# If you do list(fibonacci()) without islice: infinite loop, memory exhaustion,
# crash. The generator produces values forever — there's no StopIteration.
# itertools.islice is the safe way to consume a bounded number of items
# from an infinite iterator.
```

> [!question]- Q5. You have a pipeline: read lines from a file → filter lines containing a keyword → transform each line → write to output. Implement this as a generator pipeline. What's the memory advantage over doing each step as a list operation?
**Answer:**
```python
def read_lines(path):
    with open(path) as f:
        for line in f:
            yield line

def filter_lines(lines, keyword):
    for line in lines:
        if keyword in line:
            yield line

def transform(lines):
    for line in lines:
        yield line.strip().upper()

def process(input_path, output_path):
    lines = read_lines(input_path)
    lines = filter_lines(lines, "ERROR")
    lines = transform(lines)
    with open(output_path, 'w') as f:
        for line in lines:
            f.write(line + "\n")
```
Memory advantage: at any point, only one line is in memory — the pipeline is fully lazy. Each `yield` passes one item through the chain. Contrast with list-based: `lines = f.readlines()` → `lines = [l for l in lines if keyword in l]` → `lines = [transform(l) for l in lines]` — each step creates a new list, so at peak you have 3× the file size in memory. For a 1GB log file, the generator pipeline uses ~KB of memory while the list approach uses ~3GB.

## Related
[[redemption/python/basics]]
[[functions-and-scope]]
[[context-managers]]
[[data-structures-and-complexity]]

#status/new