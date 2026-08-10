# OOP and Dunder Methods

## What it is
Python's object model is built on dunder (double-underscore) methods — special methods like `__init__`, `__getattr__`, `__call__`, `__enter__`, and `__iter__` that the interpreter calls implicitly when you use operators, indexing, iteration, or context managers. Understanding the full contract of these methods — when they're called, what they must return, and what happens if you get them wrong — is what separates "I can write a class" from "I understand how Python objects actually work." This file also covers the method resolution order (MRO), which determines which method gets called in multiple inheritance — a topic that's deceptively simple until it isn't.

## Why it matters
AI-generated code tends to use classes as data containers (essentially glorified dicts) without leveraging Python's object model. But the real power — and the interview questions — come from understanding: why `__getattr__` vs `__getattribute__` matters, how `__new__` differs from `__init__`, why `__hash__` must be consistent with `__eq__`, and how C3 linearization determines MRO. In system design interviews, being able to explain why a custom descriptor or metaclass solves a problem (and when not to use one) signals deep understanding. And in practice, getting `__hash__` and `__eq__` wrong silently breaks sets and dicts — the kind of bug that surfaces months later as "why are there duplicate objects in my set?"

## Core example

### `__new__` vs `__init__` — the creation vs initialization distinction

```python
class Point:
    def __new__(cls, x, y):
        # __new__ is a static method that creates and returns the instance
        # It's called BEFORE __init__ and controls whether an instance is created
        print(f"__new__ called with cls={cls}, x={x}, y={y}")
        instance = super().__new__(cls)
        return instance  # MUST return an instance of cls for __init__ to run

    def __init__(self, x, y):
        # __init__ initializes the already-created instance
        # Returns None — it cannot return anything else
        print(f"__init__ called with x={x}, y={y}")
        self.x = x
        self.y = y

p = Point(1, 2)
# __new__ called with cls=<class '__main__.Point'>, x=1, y=2
# __init__ called with x=1, y=2

# __new__ is used for: immutable types (int, str, tuple subclasses),
# singletons, metaclasses, and custom allocation patterns.
# For 99% of classes, you only need __init__.
```

The critical detail: `__new__` returns the instance. If `__new__` does NOT return an instance of `cls` (e.g., returns `None` or an instance of a different class), `__init__` will NOT be called. This is how immutable types like `int` and `str` work — they override `__new__` to return cached or canonical instances, and `__init__` never runs because the object is already fully constructed.

### `__getattr__` vs `__getattribute__` — the subtle but crucial difference

```python
class Debug:
    def __getattribute__(self, name):
        # Called for EVERY attribute access — even ones that exist
        print(f"__getattribute__ accessing: {name}")
        return super().__getattribute__(name)  # MUST call super to actually get it

    def __getattr__(self, name):
        # Called ONLY when normal lookup fails (attribute not found)
        print(f"__getattr__ called for missing: {name}")
        return f"<missing: {name}>"

d = Debug()
d.existing = 42
print(d.existing)     # __getattribute__ → 42 (normal lookup succeeds)
print(d.missing)      # __getattribute__ fails → __getattr__ → "<missing: missing>"
```

`__getattribute__` is called for **every** attribute access. If you override it incorrectly, you can easily create infinite recursion or break all attribute access. `__getattr__` is only called when the attribute isn't found through normal means — it's the fallback. The rule: use `__getattr__` for lazy loading or dynamic attributes. Use `__getattribute__` only when you need to intercept ALL access (e.g., access logging, proxy objects) — and always delegate to `super().__getattribute__` to avoid breaking everything.

### `__eq__` and `__hash__` — the contract that breaks sets and dicts

```python
class User:
    def __init__(self, id, name):
        self.id = id
        self.name = name

    def __eq__(self, other):
        if not isinstance(other, User):
            return NotImplemented
        return self.id == other.id

    # Without __hash__, Python sets __hash__ = None when __eq__ is defined
    # This makes the object unhashable — can't be in a set or dict key

# u1 = User(1, "Alice")
# u2 = User(1, "Alice")
# print(u1 == u2)  # True
# {u1: "value"}    # TypeError: unhashable type: 'User'

# Fix: define __hash__ consistent with __eq__
class User:
    def __init__(self, id, name):
        self.id = id
        self.name = name

    def __eq__(self, other):
        if not isinstance(other, User):
            return NotImplemented
        return self.id == other.id

    def __hash__(self):
        # Objects that compare equal must have the same hash
        # Since equality depends on id, hash must depend on id
        return hash(self.id)

u1 = User(1, "Alice")
u2 = User(1, "Alice")
print(hash(u1) == hash(u2))  # True — consistent with __eq__
s = {u1, u2}
print(len(s))  # 1 — u1 and u2 are considered the same element
```

The contract: **if `a == b`, then `hash(a) == hash(b)`.** The reverse is NOT required — hash collisions are allowed (that's why dicts handle them). But if two equal objects have different hashes, they'll end up in different buckets of a dict/set, and lookups will fail silently. This is one of the hardest bugs to diagnose because the symptoms look like "my set has duplicates" or "my dict key doesn't work." The rule: if you define `__eq__`, define `__hash__` — and make sure equal objects hash to the same value. If your object is mutable and its hash-relevant fields can change, don't make it hashable — changing the hash while in a dict/set breaks the data structure.

### Method Resolution Order (MRO) — C3 linearization

```python
class A:
    def method(self):
        print("A.method")

class B(A):
    def method(self):
        print("B.method")
        super().method()

class C(A):
    def method(self):
        print("C.method")
        super().method()

class D(B, C):
    def method(self):
        print("D.method")
        super().method()

d = D()
d.method()
# Output: D.method → B.method → C.method → A.method
# The MRO is: D → B → C → A → object

print(D.__mro__)
# (<class '__main__.D'>, <class '__main__.B'>, <class '__main__.C'>,
#  <class '__main__.A'>, <class 'object'>)

# Python uses C3 linearization to determine MRO. The algorithm ensures:
# 1. A class appears before its parents
# 2. The order of base classes is preserved (B before C in D(B, C))
# 3. Monotonicity — adding a class doesn't reorder existing relationships

# If C3 can't produce a consistent order, Python raises TypeError:
# class X(A, B): pass  # where B inherits from A — would create inconsistency
```

The `super()` call doesn't just call the parent class — it follows the MRO. In single inheritance, this is intuitive. In multiple inheritance, `super()` calls the *next* class in the MRO, not necessarily the parent. This is why `B.method()` calling `super().method()` ends up calling `C.method`, not `A.method` — because in D's MRO, C comes after B. This is the "cooperative multiple inheritance" pattern: every class in the hierarchy must use `super()` consistently for the MRO to work correctly. If any class skips `super()` and calls the parent directly, it breaks the chain.

### Descriptors — the mechanism behind properties, methods, and `staticmethod`

```python
# A descriptor is any class that defines __get__, __set__, or __delete__
# When a descriptor is an attribute of a class, accessing that attribute
# triggers the descriptor's methods instead of returning the descriptor object

class LoggedAttribute:
    def __set_name__(self, owner, name):
        self.name = name  # Called at class creation time — knows its own name

    def __get__(self, obj, objtype=None):
        if obj is None:
            return self  # Accessed via class, not instance
        print(f"Getting {self.name}")
        return obj.__dict__.get(self.name)

    def __set__(self, obj, value):
        print(f"Setting {self.name} = {value}")
        obj.__dict__[self.name] = value

class Person:
    name = LoggedAttribute()
    age = LoggedAttribute()

p = Person()
p.name = "Alice"  # "Setting name = Alice"
p.age = 30        # "Setting age = 30"
print(p.name)     # "Getting name" then "Alice"

# This is how @property works internally — property is a built-in descriptor
# that defines __get__ and __set__ to intercept attribute access
```

Descriptors are the mechanism behind `@property`, `@classmethod`, `@staticmethod`, and `functools.cached_property`. You rarely need to write your own — but understanding that `@property` is a descriptor explains why properties can't be pickled easily, why they behave differently in subclasses, and why you can't use `@property` on instance attributes (they're class-level descriptors).

### `__call__` — making instances callable

```python
class Counter:
    def __init__(self):
        self.count = 0

    def __call__(self, increment=1):
        self.count += increment
        return self.count

c = Counter()
print(c())       # 1 — calling the instance like a function
print(c(5))      # 6
print(c.count)   # 6 — the state is preserved

# This is how stateful decorators work — the decorator returns a callable
# object that maintains state between calls

# Also useful for: function-like objects with configuration, neural network
# modules (PyTorch's nn.Module uses __call__ to invoke __forward__),
# and any situation where you want "a function with persistent state"
```

## Common mistakes / gotchas

- **Defining `__eq__` without `__hash__`** — Python automatically sets `__hash__ = None` when you define `__eq__`, making the object unhashable. If you need the object in a set or as a dict key, you must define `__hash__` explicitly — and it must be consistent with `__eq__`.
- **`__getattr__` infinite recursion** — if `__getattr__` accesses `self.attr` and that attribute doesn't exist, it calls `__getattr__` again → infinite recursion. Use `object.__getattribute__(self, name)` or access `self.__dict__` directly to avoid this.
- **`__getattribute__` breaks everything if misused** — since it's called for every attribute access, even `self.x` inside `__getattribute__` triggers another call. Always use `super().__getattribute__(name)` or `object.__getattribute__(self, name)` for actual attribute retrieval.
- **`__init__` returning a non-None value** — `__init__` must return `None`. If it returns anything else, Python raises `TypeError: __init__ should return None`. This is a common mistake when people confuse `__init__` with `__new__`.
- **`__new__` doesn't return an instance of cls** — if `__new__` returns something that's not an instance of the class, `__init__` won't be called. This is intentional (for immutable types and singletons) but surprising when you didn't mean to do it.
- **`super()` in `__init__` with multiple inheritance** — if one class in the MRO doesn't call `super().__init__()`, the chain stops and subsequent classes' `__init__` methods are never called. This is the "cooperative multiple inheritance" requirement — every class must participate.
- **Mutable objects as `__hash__` inputs** — if a field used in `__hash__` can change after the object is placed in a set/dict, the hash changes and the object becomes unreachable. Either make the object immutable or don't define `__hash__`.

## Practice

> [!question]- Q1. What happens when you define both `__eq__` and `__hash__` but make `__hash__` return a constant value (e.g., `return 42`)? Is this valid? What are the performance implications?
**Answer:** This is valid — Python only requires that equal objects have equal hashes. It does NOT require that unequal objects have different hashes. Returning a constant means all objects hash to the same bucket, turning dict/set lookups from O(1) average into O(n) worst case (all entries in one bucket). The data structure still works correctly — it just degrades to a linked list lookup for every operation. This is a valid but pathological implementation. It's useful to understand because it demonstrates that hash collisions are handled correctly by Python — correctness is preserved, performance is not.

> [!question]- Q2. You have a class with `__getattr__` that returns a default value for any missing attribute. Why does `hasattr(obj, 'missing')` return `True` in this case, and how do you fix it?
**Answer:** `hasattr` works by trying to access the attribute and catching `AttributeError`. If `__getattr__` returns a value for any missing name, no `AttributeError` is raised, so `hasattr` returns `True` for everything. To fix this, `__getattr__` should raise `AttributeError` for names it doesn't specifically handle, rather than returning a default for everything. The pattern: check if the requested name is in your handled set, and if not, `raise AttributeError(name)`. This preserves the contract that `hasattr` and `getattr` behave correctly.

> [!question]- Q3. Explain why `__slots__` exists, what it does, and when you should (and shouldn't) use it.
**Answer:** `__slots__` tells Python not to create a `__dict__` for instances, instead allocating fixed-size storage for the named attributes. This saves memory (no per-instance dict overhead) and prevents accidental attribute creation. Use it when you have many instances (millions) of a simple data class and memory is a concern. Don't use it when: you need dynamic attribute assignment, you're using multiple inheritance with conflicting `__slots__`, or you want to preserve the ability to add attributes at runtime. `__slots__` also breaks pickling by default and makes `__dict__` unavailable, so any code relying on `vars(obj)` or dynamic attribute inspection will fail.

> [!question]- Q4. In this MRO, what does `super().method()` call from each class? Draw the MRO and trace the calls.
```python
class A:
    def method(self): print("A"); super().method()
class B:
    def method(self): print("B"); super().method()
class C(A, B):
    def method(self): print("C"); super().method()
class D(C):
    def method(self): print("D"); super().method()

D().method()
```
**Answer:** MRO of D: D → C → A → B → object (C3 linearization preserves C's base order A then B). Output: D → C → A → B. When D.method calls super(), it goes to C. C.method calls super() → goes to A (next in MRO after C). A.method calls super() → goes to B. B.method calls super() → goes to object, which has no method → AttributeError. If object had a method, it would continue. The key insight: `super()` follows the MRO, not the inheritance tree. A's `super()` doesn't call B because A doesn't inherit from B — it calls B because in D's MRO, B comes after A.

> [!question]- Q5. Write a `cached_property` descriptor that computes a value once and caches it. Explain why `functools.cached_property` exists and why you can't just use `@property` with a manual cache dict.
**Answer:**
```python
class cached_property:
    def __init__(self, func):
        self.func = func
        self.attrname = None

    def __set_name__(self, owner, name):
        self.attrname = name

    def __get__(self, obj, objtype=None):
        if obj is None:
            return self
        if self.attrname is None:
            raise TypeError("Cannot use cached_property instance without proper __set_name__")
        try:
            return obj.__dict__[self.attrname]
        except KeyError:
            value = obj.__dict__[self.attrname] = self.func(obj)
            return value

    def __set__(self, obj, value):
        raise AttributeError("cached property is read-only")
```
The reason `functools.cached_property` exists: `@property` recomputes on every access. If you want to cache, you'd normally add a check in the property body — but that clutters the logic. A descriptor separates the caching concern from the computation. A manual cache dict on the class or instance works but has issues: (1) cache key collisions if multiple properties share a dict, (2) no clean way to invalidate, (3) the cache persists even if the object's state changes. `cached_property` stores the cached value in the instance's `__dict__` under the property name, which shadows the descriptor on subsequent accesses — making it both efficient and simple. The descriptor is only consulted once; after that, the instance dict has the value directly.

## Related
[[redemption/python/basics]]
[[functions-and-scope]]
[[decorators]]
[[context-managers]]
[[memory-management-and-gc]]

#status/new