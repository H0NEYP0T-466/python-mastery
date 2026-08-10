# Typing and Type Hints

## What it is
Python's type hinting system (PEP 484, introduced in Python 3.5, enhanced by PEPs 526, 544, 563, 585, 586, 593, 604, 612, 613, 646, 655, 675, 692, 695, and 705) provides static type annotations that are checked by tools like mypy, pyright, and ruff — not by the Python interpreter at runtime. The type system includes generics, protocols (structural typing), type variables, bounded types, literal types, type guards, and variadic generics. This file covers the mechanics of how type checking works, what the annotations mean at runtime (hint: nothing — they're ignored), and when typing helps vs. when it's overhead.

## Why it matters
Type hints are increasingly standard in production Python codebases. FastAPI uses Pydantic models (which are built on type hints) for request/response validation and auto-documentation. In interviews, type system questions test whether you understand generics, protocols, and the difference between static and runtime typing. But more practically: type hints catch bugs before runtime, improve code readability, and enable better IDE autocomplete. The key is understanding that types are optional, gradual, and checked by external tools — not enforced by Python itself. Using them well means catching real bugs without drowning in annotation overhead.

## Core example

### Type hints are not enforced at runtime

```python
def greet(name: str) -> str:
    return f"Hello, {name}"

# These all work at runtime — Python ignores the type hints:
greet("Alice")        # "Hello, Alice" ✓
greet(42)             # "Hello, 42" ✓ — no error at runtime!
greet(None)           # "Hello, None" ✓ — still works

# The type hints are stored in __annotations__ but not used by Python:
print(greet.__annotations__)  # {'name': <class 'str'>, 'return': <class 'str'>}

# To actually check types, you need a static type checker:
# $ mypy script.py
# script.py:6: error: Argument 1 to "greet" has incompatible type "int"; expected "str"
# script.py:7: error: Argument 1 to "greet" has incompatible type "None"; expected "str"

# Or runtime validation (which FastAPI/Pydantic does):
from pydantic import BaseModel

class GreetRequest(BaseModel):
    name: str

# GreetRequest(name=42)  # ValidationError — pydantic validates at runtime
# GreetRequest(name="Alice")  # OK

# The key insight: type hints are hints. They're ignored by the Python
# interpreter. They're checked by mypy/pyright (static) or Pydantic
# (runtime). Python itself doesn't care. This is by design — Python
# remains dynamically typed; types are an optional layer on top.
```

### Generics — writing type-safe containers

```python
from typing import Generic, TypeVar

T = TypeVar('T')  # A type variable — can be any type

class Box(Generic[T]):
    def __init__(self, value: T):
        self.value = value
    
    def get(self) -> T:
        return self.value

# Usage:
int_box = Box(42)       # Inferred: Box[int]
str_box = Box("hello")  # Inferred: Box[str]

x: int = int_box.get()  # Type checker knows this returns int
y: str = str_box.get()  # Type checker knows this returns str

# Without Generic, the type checker wouldn't know what type get() returns.
# Generic allows you to write a class that works with any type while
# preserving type information for the specific type used.

# Multiple type variables:
K = TypeVar('K')
V = TypeVar('V')

class Mapping(Generic[K, V]):
    def get(self, key: K) -> V:
        ...

# Bounded type variables — constrain T to a specific type or subclass:
from typing import Bound

class Animal:
    def speak(self) -> str: ...

class Dog(Animal):
    def speak(self) -> str: return "woof"

T_co = TypeVar('T_co', bound=Animal)  # T must be Animal or subclass

def train(animal: T_co) -> T_co:
    animal.speak()  # Type checker knows Animal has speak()
    return animal

train(Dog())  # OK — Dog is a subclass of Animal
train("not an animal")  # Error — str is not bound to Animal
```

### `Protocol` — structural typing (duck typing with types)

```python
from typing import Protocol

# Nominal typing (the default): types are compatible if they're in the
# same inheritance hierarchy. A Dog is an Animal because it inherits
# from Animal.

# Structural typing: types are compatible if they have the same structure
# (methods/attributes), regardless of inheritance. This is duck typing
# — "if it walks like a duck and quacks like a duck, it's a duck" — but
# with static type checking.

class Drawable(Protocol):
    def draw(self) -> None: ...
    
class Circle:
    def draw(self) -> None:
        print("Drawing circle")

class Square:
    def draw(self) -> None:
        print("Drawing square")

# Circle and Square don't inherit from Drawable, but they implement
# the draw() method. With Protocol, they're considered subtypes of Drawable.

def render(shape: Drawable) -> None:
    shape.draw()

render(Circle())  # OK — Circle has draw()
render(Square())  # OK — Square has draw()

# Without Protocol, you'd need to use Any or a common base class.
# Protocol lets you define interfaces without requiring inheritance.

# This is especially useful for:
# - Libraries that accept any object with a certain interface
# - Mock objects in tests (you don't need to inherit from the real class)
# - Third-party classes you can't modify but want to type-check

# Protocols can also be generic:
from typing import Protocol, TypeVar, Generic

T = TypeVar('T')

class Container(Protocol[T]):
    def get(self) -> T: ...
    def put(self, item: T) -> None: ...

# Any class with get() returning T and put() accepting T satisfies
# Container[T], regardless of inheritance.
```

### Type guards — narrowing types at runtime

```python
from typing import TypeGuard

# When you have a union type, you need to narrow it to use specific methods:
def process(value: int | str) -> int:
    if isinstance(value, int):
        return value * 2  # Type checker knows value is int here
    return len(value)     # Type checker knows value is str here

# isinstance() is a type guard — it narrows the type for the type checker.

# For custom types, you can write your own type guard:
def is_string_list(items: list) -> TypeGuard[list[str]]:
    return all(isinstance(item, str) for item in items)

def process_strings(items: list[str | int]) -> list[str]:
    if is_string_list(items):
        # Type checker knows items is list[str] here
        return [s.upper() for s in items]
    return [str(x) for x in items]

# TypeGuard is a special return type that tells the type checker
# "if this function returns True, the argument has this type."
# This is more powerful than isinstance for complex type narrowing.

# Python 3.13+ has a simpler syntax:
# def is_string_list(items: list) -> list[str]:
#     return all(isinstance(item, str) for item in items)
# The return type annotation acts as the type guard automatically.
```

### `cast` and `assert_never` — when the type checker is wrong

```python
from typing import cast, assert_never

# cast() tells the type checker "treat this expression as this type"
# It has NO runtime effect — it's just a hint to the type checker.

def get_first(items: list) -> int:
    # The type checker doesn't know this returns an int
    # But we know from context
    return cast(int, items[0])

# Use cast sparingly — it bypasses type checking. If you're wrong,
# you get a runtime error, not a type error.

# assert_never() is for exhaustiveness checking:
from typing import Union

def handle_shape(shape: Circle | Square | Triangle) -> None:
    if isinstance(shape, Circle):
        ...
    elif isinstance(shape, Square):
        ...
    else:
        assert_never(shape)  # If execution reaches here, type error
        # If you add a new shape type (Rectangle) but forget to handle
        # it, assert_never will cause a type error at compile time
        # and a runtime error if reached.

# assert_never is the type-safe version of a default case in a switch.
# It ensures your handling is exhaustive — if you add a new variant,
# the type checker forces you to update the handling.
```

### Modern type syntax (Python 3.10+)

```python
# Python 3.10 simplified union types:
# Old: Union[int, str]
# New: int | str  (PEP 604)

# Python 3.9+ generic built-ins — no need for typing.List, typing.Dict:
# Old: List[int], Dict[str, int]
# New: list[int], dict[str, int]  (PEP 585)

# Python 3.10+ match statement with type patterns:
def process(value):
    match value:
        case int():
            print(f"Integer: {value}")
        case str():
            print(f"String: {value}")
        case list() as lst:
            print(f"List with {len(lst)} items")
        case _:
            print(f"Unknown: {value}")

# Python 3.11+ Self type:
from typing import Self

class Box:
    def add(self, item) -> Self:
        # Returns the same type as self — useful for fluent interfaces
        self.items.append(item)
        return self

# Python 3.12+ type statement and generic classes:
# type Alias = int | str  (PEP 695)
# class Box[T]: ...  (generic class without Generic base)
```

### Type hints in practice — when they help and when they don't

```python
# Type hints help most at:
# 1. Function boundaries — parameters and return types
#    def connect(host: str, port: int) -> Connection:
# 2. Data structures — models, DTOs, configuration
#    class User(BaseModel): name: str; age: int
# 3. Complex generics — containers, transformers
#    def map_values[T, U](f: Callable[[T], U], d: dict[K, T]) -> dict[K, U]:

# Type hints are overhead when:
# 1. Simple scripts with no API surface
# 2. Highly dynamic code (metaprogramming, reflection) where types
#    can't be statically determined
# 3. When the type annotations are more complex than the code itself
#    (e.g., annotating a 3-line function with a 10-line type signature)

# The gradual typing philosophy: start with function signatures, add
# more detail where it matters. You don't need 100% type coverage
# to get value. Even partial typing catches the most common bugs.

# For your FastAPI work: type hints are essential. FastAPI uses them
# for request validation, response serialization, and OpenAPI schema
# generation. Without type hints, FastAPI can't auto-generate docs
# or validate inputs. This is one case where types are not optional —
# they're part of the framework's contract.
```

## Common mistakes / gotchas

- **Thinking types are enforced at runtime** — they're not. `greet(42)` works fine at runtime even with `name: str`. You need mypy/pyright for static checking or Pydantic for runtime validation.
- **Over-annotating** — typing every local variable adds noise without benefit. Focus on function signatures and public APIs. Let type inference handle locals.
- **Using `Any` to escape the type system** — `Any` disables type checking for that value. It's the escape hatch, but overuse defeats the purpose. Use `object` or specific types instead when possible.
- **Mutable default arguments with types** — the mutable default trap ([[redemption/python/basics]]) still applies. Type hints don't prevent it: `def f(items: list[] = [])` still has the bug.
- **Confusing `Optional[X]` with `X | None`** — they're equivalent (`Optional[X] == X | None`). Use the `|` syntax in Python 3.10+. `Optional` is legacy but still widely used.
- **Generic type variables not bound** — an unbound `TypeVar('T')` can be any type. If you need to constrain it (e.g., to numbers), use `bound=Number` or multiple bounds with `Protocol`.
- **Runtime type checking with `isinstance` and generics** — `isinstance(x, list[int])` is a TypeError at runtime because generic type info is erased. Use `isinstance(x, list)` instead. Type hints are erased at runtime — they don't exist in the compiled bytecode.
- **Forward references and `from __future__ import annotations`** — in Python 3.7+, PEP 563 (or `from __future__ import annotations`) makes all annotations strings, deferring evaluation. This allows forward references (class refers to itself in type hints) without quotes. In Python 3.11+, this is the default behavior.

## Practice

> [!question]- Q1. You're writing a function that accepts either a single file path (str) or a list of paths (list[str]) and processes them. Write the type signature and implementation with proper type narrowing.
**Answer:**
```python
from pathlib import Path

def process_paths(paths: str | list[str]) -> list[Path]:
    # Narrow the type
    if isinstance(paths, str):
        paths = [paths]  # Now paths is list[str]
    
    return [Path(p) for p in paths]

# Alternative with overloads for more precise typing:
from typing import overload

@overload
def process_paths(paths: str) -> Path: ...

@overload
def process_paths(paths: list[str]) -> list[Path]: ...

def process_paths(paths: str | list[str]) -> Path | list[Path]:
    if isinstance(paths, str):
        return Path(paths)
    return [Path(p) for p in paths]
```
The overload version gives more precise typing: calling with a `str` returns `Path`, calling with `list[str]` returns `list[Path]`. The type checker knows the exact return type based on the input. Without overloads, the return type is always `Path | list[str]` and the caller must narrow. Overloads are useful when the return type depends on the input type in a way that can't be expressed with a single signature.

> [!question]- Q2. Design a type-safe `Cache` class that supports getting/setting values with type preservation. Use generics and Protocol.
**Answer:**
```python
from typing import Generic, TypeVar, Protocol, Optional
import time

K = TypeVar('K')  # Key type
V = TypeVar('V')  # Value type

class EvictionPolicy(Protocol[K, V]):
    def evict(self, cache: 'Cache[K, V]') -> tuple[K, V]: ...

class Cache(Generic[K, V]):
    def __init__(self, max_size: int = 100):
        self._data: dict[K, V] = {}
        self._access_time: dict[K, float] = {}
        self._max_size = max_size
    
    def get(self, key: K) -> Optional[V]:
        if key in self._data:
            self._access_time[key] = time.time()
            return self._data[key]
        return None
    
    def set(self, key: K, value: V) -> None:
        if len(self._data) >= self._max_size:
            self._evict()
        self._data[key] = value
        self._access_time[key] = time.time()
    
    def _evict(self) -> None:
        # Simple LRU eviction
        oldest_key = min(self._access_time, key=self._access_time.get)
        del self._data[oldest_key]
        del self._access_time[oldest_key]
```
The `Cache[K, V]` generic preserves type information: `Cache[str, User]` has `get(str) → User` and `set(str, User)`. The type checker knows the exact types based on how the cache is instantiated. The `EvictionPolicy` Protocol allows different eviction strategies (LRU, LFU, FIFO) to be plugged in without inheritance — any class implementing the `evict` method satisfies the protocol.

> [!question]- Q3. What does mypy report for this code, and why?
```python
from typing import Union

def add(a: int | float, b: int | float) -> int | float:
    return a + b

result = add(1, 2)
reveal_type(result)
```
**Answer:** mypy reports `Revealed type is "builtint | builtinfloating"`. The type checker sees that `a` and `b` can each be `int` or `float`, and the `+` operator on `int | float` returns `int | float`. Even though `add(1, 2)` clearly returns an `int`, the type checker can't narrow based on the literal values because the function signature allows `float`. The `reveal_type` is a mypy builtin that shows the inferred type. To get more precise typing, you'd need overloads:
```python
@overload
def add(a: int, b: int) -> int: ...
@overload
def add(a: int, b: float) -> float: ...
@overload
def add(a: float, b: int) -> float: ...
@overload
def add(a: float, b: float) -> float: ...
def add(a, b): return a + b
```
Now `add(1, 2)` has type `int`, `add(1, 2.0)` has type `float`, etc. This is the trade-off: precise typing requires more annotations.

> [!question]- Q4. You have a function that accepts a callback. The callback should accept an int and return a str. Write the type annotation using both `Callable` and `Protocol`. Which is more readable?
**Answer:**
```python
from typing import Callable

# Using Callable:
def process_with_callback(items: list[int], callback: Callable[[int], str]) -> list[str]:
    return [callback(item) for item in items]

# Using Protocol:
class IntToString(Protocol):
    def __call__(self, value: int) -> str: ...

def process_with_callback(items: list[int], callback: IntToString) -> list[str]:
    return [callback(item) for item in items]
```
`Callable[[int], str]` is more concise and idiomatic for simple function types. `Protocol` is more readable when the callback has a complex signature or when you want to give the callback a meaningful name. `Protocol` also allows you to add documentation to the callback interface. For simple cases, `Callable` is preferred. For complex or documented interfaces, `Protocol` is better. The choice is similar to choosing between a lambda and a named function — both work, but one is more appropriate depending on complexity.

> [!question]- Q5. Explain why type hints don't affect runtime performance, and what tools actually use type information.
**Answer:** Type hints are stored in the `__annotations__` dictionary of functions and classes but are never consulted by the Python interpreter during execution. The bytecode generated for a typed function is identical to an untyped function. Type hints are purely for static analysis tools: (1) mypy/pyright — static type checkers that analyze code without running it. (2) IDEs (PyCharm, VS Code) — use type hints for autocomplete, refactoring, and inline error detection. (3) FastAPI/Pydantic — use type hints at runtime for request validation and OpenAPI schema generation (this is the exception — they actively inspect `__annotations__`). (4) linters (ruff, flake8) — use type hints for better linting rules. (5) documentation generators (Sphinx) — use type hints in generated docs. The key insight: types don't slow down Python because they're not used at runtime (except by frameworks that explicitly opt in). This is different from languages like Java or C# where types are part of the runtime and affect performance (e.g., through JIT specialization).

## Related
[[oop-and-dunder-methods]]
[[functions-and-scope]]
[[decorators]]
[[pydantic-models-and-validation]]

#status/new