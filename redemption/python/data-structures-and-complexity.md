# Data Structures and Complexity

## What it is
Python's built-in data structures — `list`, `dict`, `set`, `tuple`, `deque`, `defaultdict`, `Counter`, `OrderedDict` (legacy), and `heapq` — each have specific performance characteristics that determine which one you reach for in a given situation. This isn't about memorizing Big-O tables. It's about understanding *why* each structure has its costs, where the boundaries are between "fast enough" and "catastrophic," and how Python's implementation choices (open-addressing dicts, dynamic array lists, hash-based sets) create behaviors that surprise you when you hit the edge cases.

## Why it matters
Choosing the wrong structure turns an O(n) lookup into O(n²) across a loop — the difference between a script that runs in 2 seconds and one that runs in 20 minutes. AI-generated code tends to default to `list` for everything because it's the most familiar, even when `set` or `dict` would be orders of magnitude faster. In interviews, the "optimal solution" often hinges on picking the right structure — and interviewers now test whether you understand *why*, not just whether you can recite the complexity table. Knowing that dict lookups are amortized O(1) but degrade during resizing, or that `list.pop(0)` is O(n) while `deque.popleft()` is O(1), is the difference between a correct answer and a "you almost got it" answer.

## Core example

### The list trap — O(n) lookup disguised as simplicity

```python
# Checking membership in a list: O(n)
items = list(range(10_000))
targets = set(range(5_000, 15_000))

# Slow — O(n * m) where m is len(targets)
count = 0
for t in targets:
    if t in items:   # scans the entire list each time
        count += 1

# Fast — O(n + m) by switching to a set
items_set = set(items)
count = sum(1 for t in targets if t in items_set)  # O(1) lookup
```

The `in` operator on a list is linear scan. On a set or dict key, it's a hash table lookup — average O(1). For 10,000 items × 5,000 lookups, the list version does ~50 million comparisons. The set version does ~15,000. This is the single most common performance bug in Python code.

### Why dict lookups are amortized O(1) — and when they're not

Python dicts use **open addressing** with a variant of linear probing (since Python 3.6, the implementation was rewritten for better cache locality and memory efficiency). When you insert a key:

1. Hash the key → get an index into the underlying array
2. If that slot is empty, place the entry there
3. If occupied (collision), probe to the next slot until you find space
4. When the table is 2/3 full, resize (double + rehash all entries)

The "amortized" in "amortized O(1)" comes from the resize cost. Inserting N items costs O(N) total, but one insertion triggers the resize — that single insertion is O(N). Spread across all insertions, it's O(1) each. But if you pre-size a dict (or set) by hinting, you avoid the resize entirely:

```python
# Pre-allocate when you know the size — avoids repeated resizing
result = {}
# Instead of growing incrementally, you can't pre-size dict directly,
# but you can avoid the worst case by understanding when resizing happens

# For lists, you CAN pre-allocate:
result = [None] * known_size  # O(1) allocation, no incremental growth
```

### `list` vs `tuple` — it's not just "immutable list"

```python
# Tuples are hashable (if contents are hashable) — can be dict keys
coord = (45.12, -90.05)
locations = {coord: "warehouse A"}  # lists can't do this

# Tuples are faster to create and iterate — fixed size, simpler memory layout
# But once created, you can't modify them

# The real difference: tuples are "records," lists are "sequences"
# A tuple represents a fixed structure: (x, y) coordinates, (name, age) record
# A list represents a homogeneous collection: [user1, user2, user3]

# Using a tuple as a record with named access:
from collections import namedtuple
Point = namedtuple("Point", ["x", "y"])
p = Point(1, 2)
print(p.x)  # 1 — more readable than p[0]

# In Python 3.9+, use typing.NamedTuple or dataclasses for richer records
```

### `deque` — the double-ended queue you didn't know you needed

```python
from collections import deque

# List pop(0) is O(n) — shifts all elements left
# Deque popleft() is O(1) — just moves a pointer

queue = deque()
queue.append(1)      # O(1) — right end
queue.appendleft(2)  # O(1) — left end
queue.popleft()      # O(1) — removes from left
queue.pop()          # O(1) — removes from right

# Also supports O(1) append/pop on both ends, making it ideal for:
# - BFS queues
# - Sliding windows (append right, pop left)
# - Undo/redo stacks (push both ends)

# Bounded deque — automatically discards old items
recent = deque(maxlen=100)
for i in range(1000):
    recent.append(i)
# Only last 100 items retained — memory-bounded, perfect for rolling windows
```

### `defaultdict` and `Counter` — specialized dict subclasses

```python
from collections import defaultdict, Counter

# defaultdict: provides a default factory for missing keys
# Avoids the "if key not in d: d[key] = []" pattern
word_counts = defaultdict(int)
for word in text.split():
    word_counts[word] += 1  # int() → 0 for missing keys

# Grouping items
by_length = defaultdict(list)
for word in words:
    by_length[len(word)].append(word)  # list() → [] for missing keys

# Counter: optimized for counting — implemented in C, faster than manual defaultdict
counts = Counter(text.split())
top_5 = counts.most_common(5)  # O(n log k) using heap internally

# Counter supports arithmetic:
c1 = Counter(a=2, b=1)
c2 = Counter(a=1, b=2)
print(c1 + c2)   # Counter(a=3, b=3) — union with addition
print(c1 - c2)   # Counter(a=1) — subtraction, keeps only positive counts
print(c1 & c2)   # Counter(a=1, b=1) — intersection (min of counts)
print(c1 | c2)   # Counter(a=2, b=2) — union (max of counts)
```

### `heapq` — priority queue with O(log n) push/pop

```python
import heapq

# Python's heapq is a min-heap — smallest element always at index 0
heap = []
heapq.heappush(heap, 5)
heapq.heappush(heap, 1)
heapq.heappush(heap, 3)
print(heapq.heappop(heap))  # 1 — always the smallest

# For a max-heap, negate values (since numbers are what's compared)
max_heap = []
heapq.heappush(max_heap, -5)
heapq.heappush(max_heap, -1)
print(-heapq.heappop(max_heap))  # 5 — largest original value

# Real use case: finding top-K elements without full sort
# Sorting is O(n log n). Heap approach is O(n log K).
import random
nums = [random.randint(1, 1000) for _ in range(10000)]
top_10 = heapq.nlargest(10, nums)  # O(n log 10) ≈ O(n) — much faster than sorted(nums)[:10]
top_10_smallest = heapq.nsmallest(10, nums)

# For streaming data where you can't hold everything in memory:
# maintain a heap of size K — push-pop keeps only the top K seen so far
```

## Common mistakes / gotchas

- **Using `list` for membership testing** — `x in lst` is O(n). If you're doing repeated lookups, use `set` (O(1)) or `dict` keys. This is the #1 performance anti-pattern.
- **`list.pop(0)` is O(n)** — it shifts every element left. Use `collections.deque` for FIFO queues.
- **Modifying a dict while iterating** — `for k in d: if cond: del d[k]` raises `RuntimeError: dictionary changed size during iteration`. Iterate over a copy: `for k in list(d):` or collect keys to delete and remove after.
- **Tuples are hashable only if all elements are hashable** — `([1, 2],)` is unhashable because the list inside is mutable. You can't use it as a dict key.
- **Dict ordering is guaranteed (Python 3.7+) but don't rely on it for logic** — insertion order is preserved, but this is an implementation detail that became a language guarantee. It's safe for iteration order, but don't use it as a sorting mechanism.
- **`set` operations create new sets** — `s1 | s2`, `s1 & s2` allocate new objects. For in-place updates, use `s1.update(s2)` or `s1 |= s2` to avoid allocation.
- **`Counter` arithmetic drops zero and negative counts** — `c1 - c2` removes keys where the result is ≤ 0. This is usually what you want, but it's a surprise if you expect all keys to persist.
- **`heapq` only provides min-heap** — for max-heap behavior, negate values. For complex objects, provide a `key` function or wrap in a tuple `(priority, item)` — but be careful: if priorities are equal, Python compares the second element, which may fail if items aren't comparable.

## Practice

> [!question]- Q1. You have a list of 1 million integers and need to find all duplicates. What's the optimal approach in terms of time and space? Compare three approaches and their trade-offs.
**Answer:** Approach 1: `Counter(lst)` then filter counts > 1 — O(n) time, O(n) space, cleanest code. Approach 2: iterate with a `seen` set, add to `duplicates` set when already seen — O(n) time, O(n) space worst case but stops tracking after first duplicate found. Approach 3: if integers are in a known small range (e.g., 0 to 100,000), use a counting array — O(n) time, O(range) space, most memory-efficient if range is small. The Counter approach is best for general cases; the counting array wins if the range is bounded and known.

> [!question]- Q2. You're implementing an LRU (Least Recently Used) cache with max size K. Describe the data structure combination you'd use and why. What are the time complexities of get and put?
**Answer:** Combine a `dict` (for O(1) key lookup) with a `collections.OrderedDict` (or in Python 3.7+, a regular dict with manual ordering). On each `get`, move the accessed key to the end (most recently used). On `put`, if at capacity, remove the first item (least recently used). Both get and put are O(1). Alternatively, `dict + doubly linked list` gives the same result with explicit control — this is what `collections.OrderedDict` implements internally. Python 3.8+ has `functools.lru_cache` which uses this pattern.

> [!question]- Q3. Why is `tuple` faster to create and iterate than `list`? Be specific about the implementation difference.
**Answer:** Tuples are immutable, so CPython can allocate a single contiguous memory block for the entire tuple and store it as a fixed-size array. Lists are dynamic arrays that over-allocate (typically 1.125× growth factor) to accommodate appends, requiring extra memory and bounds checks. Tuples also don't need methods that modify in place (`append`, `extend`, `remove`), so their C implementation is simpler. The immutability guarantee allows CPython to optimize tuple creation with a single opcode (`BUILD_LIST` vs `BUILD_TUPLE`) and enables tuple interning for small tuples.

> [!question]- Q4. You have a stream of 100 million numbers and want the top 100 largest. You can't fit all numbers in memory. Describe the algorithm and its complexity.
**Answer:** Maintain a min-heap of size 100. For each number in the stream: if heap size < 100, push; else if number > heap[0] (smallest in heap), `heapreplace` (pop smallest, push new). At the end, the heap contains the 100 largest. Time: O(n log K) where K=100 — essentially O(n). Space: O(K) — constant. This is the standard streaming top-K algorithm and is optimal for this constraint. The key insight: you never need to keep more than K elements, and a min-heap lets you efficiently evict the smallest of the current top-K.

> [!question]- Q5. What happens to dict performance when many keys have the same hash? Explain the mechanism and the worst-case complexity.
**Answer:** When keys collide (same hash), Python's open-addressing scheme probes to the next slot. If many keys share the same hash, they form a cluster in the array, and lookups degrade from O(1) to O(n) as the probe sequence grows. In the extreme case — all keys hash to the same value — dict lookups become O(n), equivalent to a linked list. This is why hash collisions are a denial-of-service vector: an attacker who can craft keys with the same hash can turn a dict lookup from O(1) into O(n), and with n insertions, O(n²). Python mitigates this with hash randomization (since Python 3.3) — the hash seed is randomized per process, making it impossible for an attacker to predict colliding keys. But if you define a custom `__hash__` that returns a constant, you're voluntarily creating this worst case.

## Related
[[redemption/python/basics]]
[[memory-management-and-gc]]
[[gil-and-threading]]
[[concurrency-patterns]]

#status/new