# Virtual Envs and Dependency Management

## What it is
Python's dependency management ecosystem has evolved from `requirements.txt` + `pip` to `pyproject.toml` + build backends (setuptools, poetry, hatch, uv) + lock files (pip-tools, poetry.lock, uv.lock). Virtual environments isolate project dependencies from each other and from the system Python. This file covers the mechanics of virtual environments (what they actually isolate), the difference between build backends and dependency managers, lock files and reproducibility, and the modern tooling landscape — including why `uv` is rapidly becoming the default choice.

## Why it matters
Dependency hell — "it works on my machine," version conflicts, unpinned dependencies breaking CI, transitive dependency vulnerabilities — is the #1 source of production incidents that aren't code bugs. In interviews, dependency management questions test whether you understand the difference between `install_requires` and dependency groups, why lock files matter, and how virtual environments actually work. For your work — every project from GPT-2 to DINOv2 to FastAPI APIs — proper dependency management means your code runs the same way in CI, on your laptop, and in production. Getting it wrong means debugging environment issues instead of writing code.

## Core example

### What a virtual environment actually is

```bash
# Creating a venv:
$ python -m venv .venv

# What this does:
# 1. Creates a directory (.venv/) with a copy of (or symlinks to) the
#    Python interpreter
# 2. Creates a site-packages/ directory inside .venv/ for installed packages
# 3. Creates activate scripts that modify PATH and PYTHONPATH to point
#    to the venv's Python and site-packages
# 4. Sets up pip and setuptools inside the venv

# Activating:
$ source .venv/bin/activate  # Linux/macOS
# Or: . .venv/bin/activate
# This modifies your shell's PATH so that 'python' and 'pip' point
# to the venv's versions instead of the system versions.

# Deactivating:
$ deactivate  # Restores the original PATH

# What's isolated:
# - Installed packages (site-packages) — each venv has its own
# - Python interpreter version (but the venv shares the same Python
#   binary via symlink — it doesn't copy the entire interpreter)
# - pip cache (partially — some cache is shared across venvs)

# What's NOT isolated:
# - Environment variables (unless explicitly set in activate script)
# - System-level packages (installed with --system or in system Python)
# - The Python version itself (venv doesn't change Python version —
#   use pyenv or tox for that)
```

### `requirements.txt` vs `pyproject.toml` — the evolution

```toml
# Old way — requirements.txt:
# requests==2.31.0
# pydantic>=2.0.0
# numpy
# 
# Problems:
# - No distinction between direct and transitive dependencies
# - No metadata (description, authors, entry points)
# - No optional dependencies (dev, test, docs)
# - No build system configuration
# - Multiple files needed for different purposes (requirements.txt,
#   requirements-dev.txt, setup.py, setup.cfg)

# New way — pyproject.toml (PEP 621):
[build-system]
requires = ["setuptools>=61.0"]
build-backend = "setuptools.build_meta"

[project]
name = "my-package"
version = "1.0.0"
description = "A sample package"
requires-python = ">=3.10"
dependencies = [
    "requests>=2.31.0",
    "pydantic>=2.0.0",
    "numpy>=1.24.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0.0",
    "black>=23.0.0",
    "mypy>=1.0.0",
]
test = [
    "pytest>=7.0.0",
    "pytest-cov>=4.0.0",
]

[project.scripts]
my-cli = "my_package.cli:main"

# Advantages:
# - Single file for all project metadata
# - Direct vs transitive dependencies are clear (dependencies = direct)
# - Optional dependencies with named groups
# - Entry points (console scripts) declared declaratively
# - Build system configuration in the same file
# - Standardized across tools (setuptools, poetry, hatch, uv all support it)
```

### Lock files — reproducibility vs flexibility

```bash
# The problem: even with pinned versions in requirements.txt,
# transitive dependencies can change. requests==2.31.0 might depend on
# urllib3>=1.21.1, and a new urllib3 version could break your code.

# Solution: lock files pin the entire dependency tree, including
# transitive dependencies, to exact versions.

# pip-tools (pip-compile):
# requirements.in (direct dependencies, loose constraints):
# requests>=2.31.0
# pydantic>=2.0.0
# 
# $ pip-compile requirements.in
# Generates requirements.txt with ALL dependencies pinned:
# certifi==2023.7.22
# charset-normalizer==3.3.0
# idna==3.4
# requests==2.31.0
# urllib3==2.0.6
# 
# To update: $ pip-compile --upgrade

# Poetry:
# pyproject.toml has dependencies with constraints
# poetry.lock has the full pinned tree
# $ poetry install  # Installs from poetry.lock
# $ poetry update   # Updates dependencies and regenerates lock

# uv (newest, fastest):
# uv.lock is the lock file
# $ uv sync  # Installs from uv.lock (like poetry install)
# $ uv lock  # Regenerate lock file (like poetry lock)
# $ uv add requests  # Add dependency and update lock

# Why lock files matter:
# - Reproducibility: same versions everywhere (dev, CI, prod)
# - Security: known versions can be scanned for vulnerabilities
# - Debugging: if a bug appears, you can reproduce the exact environment
# - CI speed: no dependency resolution needed, just install from lock

# When NOT to use lock files:
# - Libraries (packages published to PyPI) — they should NOT ship a
#   lock file because they're dependencies of other projects, and
#   locking would force specific versions on downstream users.
#   Libraries should use loose constraints in pyproject.toml.
# - Applications (deployed services) — SHOULD use lock files because
#   you control the deployment environment and need reproducibility.
```

### `uv` — the modern all-in-one tool

```bash
# uv (by Astral, the same team as ruff) is a Python package installer
# and resolver written in Rust. It's dramatically faster than pip
# (10-100x) because it resolves dependencies in parallel and caches
# everything aggressively.

# Key features:
# 1. pip-compatible: uv pip install works like pip install but faster
# 2. Project management: uv init, uv add, uv run, uv sync
# 3. Lock files: uv.lock, generated and updated automatically
# 4. Python management: uv python install (like pyenv but integrated)
# 5. Single binary: no Python dependency for uv itself

# Basic workflow:
$ uv init myproject        # Creates pyproject.toml + .gitignore
$ uv add requests          # Adds to dependencies + updates uv.lock
$ uv add --dev pytest      # Adds to dev dependencies
$ uv run python main.py    # Runs in project environment (auto-creates venv)
$ uv sync                  # Installs all dependencies from uv.lock
$ uv lock                  # Regenerate lock file

# For publishing:
$ uv build                 # Build wheel and sdist
$ uv publish               # Publish to PyPI

# Why uv is becoming the default:
# - Speed: resolves and installs in seconds, not minutes
# - Simplicity: one tool for venv, install, lock, run, publish
# - Standards-compliant: uses pyproject.toml (PEP 621), not a custom format
# - Lock files: built-in, no separate tool needed
# - Python management: integrated, no need for pyenv separately

# For your work: if you're starting a new project, use uv. It handles
# everything: venv creation, dependency installation, lock file management,
# and running scripts. The learning curve is minimal if you know pip,
# and the speed improvement is dramatic.
```

### Dependency groups and extras

```toml
# [project.optional-dependencies] in pyproject.toml defines groups
# of optional dependencies. Users can install them with:
# $ pip install "my-package[dev]"
# $ pip install "my-package[test]"

[project.optional-dependencies]
dev = [
    "black>=23.0.0",
    "mypy>=1.0.0",
    "ruff>=0.0.270",
]
test = [
    "pytest>=7.0.0",
    "pytest-cov>=4.0.0",
    "pytest-asyncio>=0.21.0",
]
docs = [
    "mkdocs>=1.5.0",
    "mkdocs-material>=9.0.0",
]
all = [
    "my-package[dev]",
    "my-package[test]",
    "my-package[docs]",
]

# The 'all' group is a common pattern — includes everything.
# For ML projects, you might have:
ml = [
    "torch>=2.0.0",
    "torchvision>=0.15.0",
    "numpy>=1.24.0",
    "scipy>=1.10.0",
]
api = [
    "fastapi>=0.100.0",
    "uvicorn>=0.23.0",
    "pydantic>=2.0.0",
]

# Users install with: pip install "my-package[ml,api]"
# This installs both ml and api groups.

# In uv, you use the same syntax:
$ uv sync --all-extras   # Installs all optional groups
$ uv sync --group ml     # Installs only the ml group
```

### Development workflows — comparing approaches

```bash
# Approach 1: Traditional pip + venv + requirements.txt
$ python -m venv .venv
$ source .venv/bin/activate
$ pip install -r requirements.txt
$ pip install -r requirements-dev.txt
# Manual management, no lock file by default, multiple files

# Approach 2: Poetry
$ poetry init          # Interactive setup
$ poetry add requests  # Adds to pyproject.toml + poetry.lock
$ poetry install       # Installs from poetry.lock
$ poetry run python main.py  # Runs in venv
# Single tool, built-in lock, custom pyproject.toml format (pre-PEP 621)

# Approach 3: uv (recommended for new projects)
$ uv init
$ uv add requests      # Adds to pyproject.toml + uv.lock
$ uv sync              # Installs from uv.lock
$ uv run python main.py
# Single tool, built-in lock, standards-compliant pyproject.toml, fast

# Approach 4: pip-tools (for existing pip-based projects)
$ pip-compile requirements.in  # Generates requirements.txt (pinned)
$ pip install -r requirements.txt
# Adds lock-like reproducibility to existing pip workflow
# Good for teams not ready to switch to poetry/uv

# For ML work specifically:
# - ML dependencies (PyTorch, TensorFlow) are large and platform-specific
# - Use uv or poetry with platform-specific lock files
# - Or use conda/mamba for complex scientific Python environments
#   (conda handles non-Python dependencies like CUDA toolkits)
# - For production deployment of ML models, use uv or pip with lock files
#   in Docker containers for reproducibility
```

## Common mistakes / gotchas

- **Not using virtual environments** — installing packages globally pollutes the system Python and causes conflicts between projects. Always use a venv.
- **Committing `__pycache__` or `.venp/` to git** — add `.venv/`, `__pycache__/`, `*.pyc` to `.gitignore`. Virtual environments are not reproducible across machines.
- **Not using lock files for applications** — without a lock file, `pip install` resolves dependencies fresh each time, potentially pulling in breaking changes. Applications should lock; libraries should not.
- **Using `pip freeze > requirements.txt` for library projects** — `pip freeze` pins ALL dependencies including transitive ones. For libraries, this forces specific versions on users. Use `pip-compile` with a `requirements.in` that lists only direct dependencies, or declare dependencies in pyproject.toml with version ranges.
- **Mixing pip and conda** — installing some packages with pip and others with conda in the same environment can cause conflicts. If you use conda, prefer `conda install` for everything. If you must mix, install conda packages first, then pip.
- **Not pinning Python version** — `requires-python = ">=3.10"` in pyproject.toml specifies the minimum Python version. Without it, your package might be installed on an unsupported Python version. Always specify.
- **Using `--user` flag with pip** — `pip install --user` installs to the user's home directory, bypassing the venv. This defeats the purpose of virtual environments. Always activate the venv first, then install without `--user`.
- **Ignoring dependency vulnerabilities** — use `pip-audit` or `safety` to scan dependencies for known vulnerabilities. Integrate into CI. Lock files help because you know exactly which versions you're using.

## Practice

> [!question]- Q1. You're building a FastAPI application with ML inference. Design the dependency structure with appropriate groups. What goes in each group and why?
**Answer:**
```toml
[project.dependencies]
fastapi = ">=0.100.0"
uvicorn = ">=0.23.0"
pydantic = ">=2.0.0"
torch = ">=2.0.0"
torchvision = ">=0.15.0"
numpy = ">=1.24.0"

[project.optional-dependencies]
dev = [
    "ruff = ">=0.0.270"",
    "mypy = ">=1.0.0"",
    "black = ">=23.0.0"",
]
test = [
    "pytest = ">=7.0.0"",
    "pytest-asyncio = ">=0.21.0"",
    "httpx = ">=0.24.0"",  # For TestClient
]
monitoring = [
    "prometheus-client = ">=0.17.0"",
    "sentry-sdk = ">=1.28.0"",
]
```
Core dependencies (fastapi, uvicorn, pydantic, torch) are required for the app to run — they go in `dependencies`. Dev tools (linters, type checkers, formatters) are only needed during development — `dev` group. Test tools are only needed for running tests — `test` group. Monitoring tools are optional for production — `monitoring` group. This structure allows a minimal production install (`uv sync` without extras), a full dev environment (`uv sync --all-extras`), and a CI environment (`uv sync --group test`). The key principle: only install what you need for each environment.

> [!question]- Q2. You have a project that works fine locally but fails in CI with "ModuleNotFoundError: No module named 'X'". The module X is used in the code but not listed in pyproject.toml. Diagnose and explain why this happens.
**Answer:** This is a "undeclared dependency" bug. Locally, you probably installed X manually with `pip install X` at some point, and it ended up in your venv. But it's not declared in pyproject.toml, so when CI creates a fresh environment and runs `uv sync` or `pip install -e .`, X is not installed. The code imports X but it's not available. Fix: add X to the appropriate dependency group in pyproject.toml. To prevent this: use `pip check` to verify all imports are satisfied by declared dependencies, or use tools like `pipreqs` or `pigar` to scan imports and compare with declared dependencies. In CI, run with a completely fresh venv (not reusing a cached one) to catch these bugs. The root cause: relying on implicitly installed transitive dependencies instead of explicitly declaring direct dependencies.

> [!question]- Q3. Explain the difference between `dependencies`, `optional-dependencies`, and `dev-dependencies` in pyproject.toml. When installing a package as a dependency of another package, which groups are installed?
**Answer:** `dependencies` are required — they're always installed when the package is installed. `optional-dependencies` are groups that users can opt into with `pip install "pkg[extra]"`. `dev-dependencies` (conventionally in `[project.optional-dependencies.dev]`) are for development tools. When you install a package as a dependency of another package (e.g., package A depends on package B), only B's `dependencies` are installed — NOT B's optional-dependencies or dev-dependencies. This is by design: if B's dev dependencies (pytest, black) were installed whenever someone installed A, every package would pull in the entire dev toolchain of all its dependencies. The rule: optional and dev dependencies are only installed when you explicitly install the package with those extras (e.g., `pip install "B[dev]"`). This is why you should never put runtime dependencies in dev dependencies — they won't be available to downstream users.

> [!question]- Q4. You need to deploy a FastAPI + ML application to production. Compare Docker with uv vs Docker with pip in terms of build time, image size, and reproducibility.
**Answer:** Docker with uv: use `uv sync --frozen` in the Dockerfile to install from the locked uv.lock file. uv is written in Rust and installs packages 10-100x faster than pip, dramatically reducing build time. The resulting image size is similar (same packages installed). Reproducibility is excellent — uv.lock pins all versions. Docker with pip: use `pip install -r requirements.txt` — slower resolution and installation, especially for large ML packages. If requirements.txt is not a lock file (just direct dependencies), pip resolves each time, causing variability. If it IS a lock file (from pip-compile), reproducibility is good but pip is slower. The uv approach is strictly better for build time and equivalent for image size and reproducibility. The only caveat: uv is newer and less battle-tested in production CI/CD than pip, but it's rapidly maturing. For new projects, uv is the recommended choice.

> [!question]- Q5. What is PEP 723 (script metadata) and how does it change the way you write one-off Python scripts?
**Answer:** PEP 723 (added in Python 3.13) allows you to embed dependency metadata directly in a Python script using a `# /// script` comment block. This lets you run a script with its dependencies automatically installed, without creating a project or venv manually. Example:
```python
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "requests>=2.31",
#   "rich>=13",
# # ///
import requests
from rich import print
response = requests.get("https://api.example.com")
print(response.json())
```
Run with: `uv run script.py` or `python script.py` (with uv's runner). uv reads the embedded metadata, creates a temporary environment with the specified dependencies, and runs the script. This changes one-off scripts from "I need to set up a venv and install deps first" to "just run the script." It's ideal for data analysis scripts, migration scripts, and any standalone Python file that needs dependencies. For your work: useful for quick data preprocessing scripts, experiment runners, and deployment scripts that need specific packages but don't warrant a full project structure.

## Related
[[modules-and-packaging]]
[[deployment-docker-uvicorn]]
[[project-folder-structure]]
[[env-and-config-management]]

#status/new