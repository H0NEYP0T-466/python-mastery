# Modules and Packaging

## What it is
Python's module system — `import`, `from ... import`, packages (`__init__.py`), `sys.path`, absolute vs relative imports, and the `__name__ == "__main__"` idiom — determines how your code is organized, discovered, and executed. The packaging layer — `pyproject.toml`, `setup.py` (legacy), `pip`, virtual environments, and publishing to PyPI — determines how your code is distributed and installed. This file covers both: the mechanics of importing (what actually happens when you `import x`) and the modern packaging landscape (why `pyproject.toml` replaced `setup.py` and how to structure a real project).

## Why it matters
Import errors — `ModuleNotFoundError`, `ImportError`, circular import errors — are among the most common Python bugs. AI-generated code often suggests `sys.path.insert(0, ...)` as a fix, which masks the real problem. Understanding how Python resolves imports (the `sys.path` order, `__path__` for packages, `__init__.py` execution) means you can debug import issues instead of guessing. And in real projects, packaging decisions (editable installs, namespace packages, dependency pinning) directly affect reproducibility, CI/CD, and deployment. Interview questions about imports test whether you understand the mechanism, not just the syntax.

## Core example

### What happens when you `import x`

```python
# When you run: import mymodule

# 1. Check sys.modules — a cache of already-imported modules
#    If mymodule is in sys.modules, return it immediately (no re-execution)

# 2. Search for the module in sys.path (in order):
#    - The directory of the script being run (or current directory for interactive)
#    - PYTHONPATH environment variable directories
#    - Installation-dependent default paths (site-packages, stdlib)

# 3. When found, create a new module object, execute the module's code
#    top-to-bottom (this is why imports can have side effects), and
#    store the result in sys.modules

# 4. Bind the name 'mymodule' in the current namespace to the module object

# This is why:
# - Imports are cached — importing the same module twice doesn't re-execute it
# - Circular imports can fail — if module A imports B, and B imports A,
#   A is partially initialized when B tries to import it
# - Import-time side effects happen once — top-level code in a module
#   runs only on first import
```

The `sys.modules` cache is the key to understanding circular imports. When A imports B, and B imports A, Python finds A in `sys.modules` (it's being initialized) and returns the partially-initialized module. If B tries to access something in A that hasn't been defined yet (because A's top-to-bottom execution hasn't reached it), you get `AttributeError: module 'A' has no attribute 'x'`. The fix: move imports inside functions (so they happen after both modules are fully loaded) or restructure to avoid the cycle.

### `__init__.py` — what it does and when you need it

```python
# In Python 3.3+, packages are "namespace packages" by default —
# you don't strictly need __init__.py for a directory to be a package.
# But __init__.py is still useful for several reasons:

# 1. Package-level initialization — code that runs when the package is imported
# mypackage/__init__.py:
print("Initializing mypackage")
from . import submodule  # Make submodule available as mypackage.submodule
VERSION = "1.0.0"

# Now: import mypackage → prints "Initializing mypackage"
#       mypackage.VERSION → "1.0.0"
#       mypackage.submodule → accessible

# 2. Controlling the public API — __all__ defines what 'from package *' imports
# __init__.py:
__all__ = ["public_function", "PublicClass"]  # Names exported by 'from mypackage import *'

# 3. Simplifying imports — re-export submodules so users don't need deep paths
# __init__.py:
from .database import connect, Query  # Users can do: from mypackage import connect
# Instead of: from mypackage.database import connect

# Without __init__.py, the directory is still importable (namespace package),
# but you lose package-level initialization, __all__, and re-exports.
# For regular packages, include __init__.py — it's the standard practice.
```

### Absolute vs relative imports

```python
# Inside mypackage/submodule.py:

# Absolute import — full path from the project root
from mypackage.utils import helper  # Always works, unambiguous

# Relative import — relative to the current package
from .utils import helper  # '.' means current package (mypackage)
from .. import other_sibling  # '..' means parent package

# Relative imports only work inside packages (not in top-level scripts).
# They're preferred within a package because they're resilient to renaming —
# if you rename 'mypackage' to 'newname', relative imports still work.
# Absolute imports require updating every import statement.

# The rule: use absolute imports for cross-package imports, relative
# imports for intra-package imports. This is PEP 8's recommendation.

# Common error: running a module inside a package as a script
# $ python mypackage/submodule.py  → Relative imports fail!
# Because the module is run as __main__, not as part of the package.
# Fix: run as a module instead:
# $ python -m mypackage.submodule  → Works correctly
```

### `__name__ == "__main__"` — the execution guard

```python
# In a module file:
def main():
    print("Running as script")

if __name__ == "__main__":
    main()

# When the file is run directly as a script:
# $ python myfile.py
# → __name__ is set to "__main__" → main() runs

# When the file is imported:
# → __name__ is set to the module name ("myfile") → main() does NOT run

# This is the standard pattern for making a module usable both as
# an imported library and as a standalone script. Without the guard,
# any top-level code runs on import — which can cause side effects
# when you only wanted to import a function.

# Important: __name__ is set by Python based on HOW the module is loaded,
# not by the file's contents. You can't "trick" it by setting __name__.
```

### `sys.path` — manipulating the import search path

```python
import sys
print(sys.path)
# ['', '/usr/lib/python3.11', '/usr/lib/python3.11/lib-dynload',
#  '/home/user/.local/lib/python3.11/site-packages', ...]

# The empty string '' represents the current directory.
# Modifying sys.path at runtime:
sys.path.insert(0, "/some/other/path")  # Add to front of search path

# This works but is generally a code smell — it means your project
# structure doesn't match Python's import expectations. Better solutions:
# 1. Install your package in editable mode: pip install -e .
# 2. Use proper package structure with __init__.py
# 3. Set PYTHONPATH environment variable
# 4. Use a .pth file in site-packages

# The only legitimate runtime sys.path manipulation: plugins or
# dynamically discovered modules that aren't part of the main codebase.
```

### Modern packaging — `pyproject.toml`

```toml
# pyproject.toml — the modern standard (PEP 517/518/621)
[build-system]
requires = ["setuptools>=61.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "my-package"
version = "1.0.0"
description = "A sample package"
readme = "README.md"
requires-python = ">=3.10"
dependencies = [
    "requests>=2.28.0",
    "pydantic>=2.0.0",
]

[project.optional-dependencies]
dev = ["pytest>=7.0.0", "black>=23.0.0", "mypy>=1.0.0"]
test = ["pytest>=7.0.0", "pytest-cov>=4.0.0"]

[project.scripts]
my-cli = "my_package.cli:main"  # Console script entry point

[tool.setuptools.packages.find]
where = ["src"]  # If using src/ layout

# Key differences from legacy setup.py:
# - build-system specifies the build backend (setuptools, poetry, hatch, etc.)
# - [project] uses standardized metadata (PEP 621) instead of setuptools-specific kwargs
# - Dependencies are declared as a list, not install_requires
# - Entry points use [project.scripts] instead of entry_points={}
# - No Python code to execute — it's declarative, not imperative
```

### Project layouts — flat vs `src/`

```
# Flat layout (simpler, common for smaller projects):
my-package/
├── my_package/
│   ├── __init__.py
│   └── module.py
├── tests/
├── pyproject.toml
└── README.md

# src/ layout (safer, prevents accidental import of local dir vs installed package):
my-package/
├── src/
│   └── my_package/
│       ├── __init__.py
│       └── module.py
├── tests/
├── pyproject.toml
└── README.md

# The src/ layout prevents a subtle bug: when you run tests from the
# project root, Python finds the local 'my_package/' directory before
# the installed package. This means tests pass against the local source
# but fail against the installed distribution. With src/, the local
# package isn't directly importable from the root — you must install
# it, which tests the actual distributed package.
#
# For most projects, src/ layout is the safer choice. It's recommended
# by PyPA and used by most major Python projects.
```

## Common mistakes / gotchas

- **Circular imports** — module A imports B, B imports A. The partially-initialized module causes `AttributeError`. Fix: move imports inside functions, or restructure to extract shared code into a third module.
- **Import-time side effects** — code at module level runs on first import. If it's slow (loading models, connecting to databases), it slows down every import. Move heavy initialization to functions or lazy imports.
- **`from module import *`** — pollutes the namespace and makes it unclear where names come from. Avoid in production code. If you must use it, define `__all__` in the source module to control what's exported.
- **Relative imports in a top-level script** — `from . import x` fails when the file is run as `python script.py` because the script isn't part of a package. Run with `python -m package.script` instead.
- **Mutable state at module level** — module-level variables are shared across all importers. If you modify them, the change is visible everywhere. This is a common source of bugs in tests that share state.
- **`sys.path.insert(0, ...)` as a fix** — this masks the real problem: your package isn't installed properly. Use `pip install -e .` for development instead.
- **Forgetting `__init__.py` in subdirectories** — while namespace packages work without it, many tools (test runners, linters, IDEs) expect `__init__.py` for proper package detection. Include it.
- **Confusing `import x` with `from x import y`** — `import x` binds the name `x` in your namespace. `from x import y` binds `y` directly. If `x` is a module and you do `from x import y`, then `x` is NOT in your namespace — only `y` is.

## Practice

> [!question]- Q1. You have a project with this structure:
```
project/
├── app/
│   ├── __init__.py
│   ├── main.py
│   └── utils.py
└── tests/
    └── test_main.py
```
`test_main.py` does `from app.main import run` but gets `ModuleNotFoundError: No module named 'app'`. Why, and what are three ways to fix it?
**Answer:** The error occurs because when running `pytest` from the `project/` directory, Python's `sys.path` doesn't include the project root, so it can't find the `app` package. Three fixes: (1) Run pytest from the project root with `PYTHONPATH=.` set: `PYTHONPATH=.` pytest. (2) Add a `conftest.py` in `project/` that modifies `sys.path` to include the root. (3) Install the package in editable mode: create a `pyproject.toml` and run `pip install -e .`, which makes `app` importable from anywhere. The cleanest long-term solution is option 3 — it matches how the package will be used in production.

> [!question]- Q2. Explain the difference between `importlib.import_module("x")` and the `import x` statement. When would you use the dynamic form?
**Answer:** `import x` is a statement that resolves the module name at compile time and binds it in the current namespace. `importlib.import_module("x")` is a function call that resolves the module at runtime — the module name can be a variable. Use dynamic imports when: the module name is determined at runtime (e.g., plugin systems, configuration-driven imports), you need to handle import failures gracefully (catch `ModuleNotFoundError`), or you're implementing lazy loading. The `import` statement is preferred when the module is known at code-writing time — it's more readable, allows IDE autocomplete, and enables static analysis tools.

> [!question]- Q3. What happens when you modify a module-level variable after importing? Is the change visible to other modules that imported it? Demonstrate with code.
**Answer:** Yes — module-level variables are shared across all importers. When you `import config` and then modify `config.DEBUG = True`, any other module that has `import config` sees the change because they all reference the same module object in `sys.modules`. This is a common source of bugs in tests that modify global configuration and don't reset it. The fix: use a class with instance state, or provide a setter function that validates changes, or use `contextvars` for context-specific state. The module-level singleton pattern is convenient but creates hidden global state.

> [!question]- Q4. You're building a CLI tool that should be installable via `pip install` and run as `mytool`. Describe the exact `pyproject.toml` configuration and project structure needed.
**Answer:**
```toml
[build-system]
requires = ["setuptools>=61.0"]
build-backend = "setuptools.build_meta"

[project]
name = "mytool"
version = "1.0.0"
dependencies = ["click>=8.0.0"]

[project.scripts]
mytool = "mytool.cli:cli_main"
```
Project structure:
```
mytool/
├── src/
│   └── mytool/
│       ├── __init__.py
│       └── cli.py      # contains cli_main() function
├── pyproject.toml
└── README.md
```
When installed (`pip install .`), the `[project.scripts]` entry creates a console script `mytool` that calls `cli_main()` from `mytool.cli`. The `src/` layout ensures the package is properly installed before being importable. The entry point function should be minimal — parse CLI args and call the main logic from a separate function, making it testable without invoking the CLI.

> [!question]- Q5. Why does `from module import *` respect `__all__` but direct `import module` doesn't? What happens if `__all__` is not defined?
**Answer:** `from module import *` explicitly checks for `__all__` in the module — it's the only import form that does. `__all__` is a list of strings naming the attributes that should be imported when using `from module import *`. If `__all__` is not defined, `import *` imports all names that don't start with underscore (`_`). Direct `import module` always imports the entire module — all names are accessible via `module.name` regardless of `__all__`. `from module import name` imports only the specific name — `__all__` is irrelevant. The purpose of `__all__` is to define the public API of a module, making `import *` predictable and allowing internal names (prefixed with `_`) to be hidden. It's a documentation tool as much as a functional one.

## Related
[[functions-and-scope]]
[[oop-and-dunder-methods]]
[[exception-handling]]
[[virtual-envs-and-dependency-management]]

#status/new