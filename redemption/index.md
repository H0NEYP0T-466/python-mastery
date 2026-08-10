# redemption — Python + FastAPI Mastery Vault

> A vault for internalizing the "why" behind Python and FastAPI — the stuff AI-generated code lets you skip.

_Updated: 2026-08-10_

## Status
#status/new — all files drafted. Progress through them in order.

## Structure

```
redemption/
├── index.md                  ← you are here
├── python/                   ← 20 files (Python mastery)
│   ├── 01-basics.md
│   ├── 02-data-structures-and-complexity.md
│   ├── 03-functions-and-scope.md
│   ├── 04-oop-and-dunder-methods.md
│   ├── 05-decorators.md
│   ├── 06-generators-and-iterators.md
│   ├── 07-context-managers.md
│   ├── 08-exception-handling.md
│   ├── 09-modules-and-packaging.md
│   ├── 10-file-io.md
│   ├── 11-gil-and-threading.md
│   ├── 12-multiprocessing.md
│   ├── 13-async-await-and-event-loop.md
│   ├── 14-concurrency-patterns.md
│   ├── 15-memory-management-and-gc.md
│   ├── 16-typing-and-type-hints.md
│   ├── 17-testing-with-pytest.md
│   ├── 18-virtual-envs-and-dependency-management.md
│   ├── 19-logging.md
│   └── 20-performance-profiling.md
└── fastapi/                  ← 25 files (FastAPI mastery)
    ├── 01-request-response-lifecycle.md
    ├── 02-routing-and-params.md
    ├── 03-pydantic-models-and-validation.md
    ├── 04-dependency-injection.md
    ├── 05-middleware.md
    ├── 06-async-endpoints-when-to-use.md
    ├── 07-background-tasks.md
    ├── 08-database-integration-async-orm.md
    ├── 09-auth-oauth2-jwt.md
    ├── 10-env-and-config-management.md
    ├── 11-project-folder-structure.md
    ├── 12-error-handling-and-exception-handlers.md
    ├── 13-rate-limiting.md
    ├── 14-caching.md
    ├── 15-logging-and-monitoring.md
    ├── 16-testing-fastapi.md
    ├── 17-deployment-docker-uvicorn.md
    ├── 18-websockets.md
    ├── 19-streaming-responses.md
    ├── 20-cron-and-scheduled-jobs.md
    ├── 21-background-workers-queues.md
    ├── 22-inference-serving-patterns.md
    ├── 23-system-design-for-apis-at-scale.md
    ├── 24-api-versioning.md
    └── 25-cors-and-security-headers.md
```

## Python Fundamentals (20 files)

| # | File | Core topic | Cross-links |
|---|------|-----------|-------------|
| 1 | [[redemption/python/basics]] | Mutable defaults, is vs ==, truthy/falsy, chained comparisons, for...else, string interning | — |
| 2 | [[data-structures-and-complexity]] | list/dict/set/tuple internals, time complexity, collections module | [[redemption/python/basics]] |
| 3 | [[functions-and-scope]] | Closures, late binding, nonlocal, global, LEGB rule, recursion limits | [[redemption/python/basics]] |
| 4 | [[oop-and-dunder-methods]] | Dunder methods, MRO, descriptors, metaclasses, slots | [[functions-and-scope]] |
| 5 | [[decorators]] | Decorator syntax, functools.wraps, class decorators, parameterized decorators, stateful decorators | [[functions-and-scope]] |
| 6 | [[generators-and-iterators]] | Iterator protocol, generator expressions, send()/throw()/close(), yield from | [[decorators]] |
| 7 | [[context-managers]] | __enter__/__exit__, contextlib, ExitStack, async context managers | [[generators-and-iterators]] |
| 8 | [[exception-handling]] | Exception hierarchy, try/except/else/finally, exception chaining, custom exceptions | [[context-managers]] |
| 9 | [[modules-and-packaging]] | Import system, sys.path, packages, __name__, relative imports, pth files | [[exception-handling]] |
| 10 | [[file-io]] | Buffering modes, text vs binary, pathlib, mmap, encoding | [[modules-and-packaging]] |
| 11 | [[gil-and-threading]] | GIL mechanics, thread switching, I/O-bound vs CPU-bound, threading module | [[file-io]], [[concurrency-patterns]] |
| 12 | [[multiprocessing]] | Process spawning, shared memory, Queue/Pipe, Pool, ProcessPoolExecutor | [[gil-and-threading]], [[concurrency-patterns]] |
| 13 | [[async-await-and-event-loop]] | Event loop, coroutines, tasks, async/await semantics, blocking the loop | [[multiprocessing]], [[concurrency-patterns]] |
| 14 | [[concurrency-patterns]] | Decision framework: threads vs processes vs async, when to use each | [[gil-and-threading]], [[multiprocessing]], [[async-await-and-event-loop]] |
| 15 | [[memory-management-and-gc]] | Refcounting, generational GC, cycles, __del__, gc module, memory profiling | [[gil-and-threading]] |
| 16 | [[typing-and-type-hints]] | Type system, generics, protocols, TypeVar, runtime type checking | [[oop-and-dunder-methods]], [[testing-with-pytest]] |
| 17 | [[testing-with-pytest]] | Fixtures, parametrization, mocking, markers, conftest, coverage | [[typing-and-type-hints]] |
| 18 | [[virtual-envs-and-dependency-management]] | venv, pip, requirements, pyproject.toml, poetry, pip-tools | [[modules-and-packaging]] |
| 19 | [[logging]] | Logging hierarchy, handlers, formatters, filters, structured logging | [[testing-with-pytest]] |
| 20 | [[performance-profiling]] | cProfile, line_profiler, memory_profiler, timeit, optimization strategies | [[memory-management-and-gc]], [[gil-and-threading]] |

## FastAPI Mastery (25 files)

| # | File | Core topic | Cross-links |
|---|------|-----------|-------------|
| 1 | [[request-response-lifecycle]] | HTTP → TCP → ASGI → routing → endpoint → response | — |
| 2 | [[routing-and-params]] | Path/query/body params, router mounting, path converters, dependencies | [[request-response-lifecycle]] |
| 3 | [[pydantic-models-and-validation]] | Pydantic v2 validation, model config, validators, serialization | [[routing-and-params]] |
| 4 | [[dependency-injection]] | Dependency system, sub-dependencies, yields/cleanup, class-based deps | [[pydantic-models-and-validation]] |
| 5 | [[middleware]] | ASGI middleware, order matters, CORS, auth middleware, timing middleware | [[dependency-injection]] |
| 6 | [[async-endpoints-when-to-use]] | When to use async def, blocking the event loop, offloading | [[middleware]], [[async-await-and-event-loop]] |
| 7 | [[background-tasks]] | FastAPI BackgroundTasks, in-process, response-sent execution | [[async-endpoints-when-to-use]] |
| 8 | [[database-integration-async-orm]] | Async DB drivers, SQLAlchemy async, Tortoise ORM, connection pooling | [[async-endpoints-when-to-use]] |
| 9 | [[auth-oauth2-jwt]] | OAuth2 password flow, JWT, refresh tokens, scopes | [[database-integration-async-orm]], [[middleware]] |
| 10 | [[env-and-config-management]] | Pydantic Settings, env vars, .env, secret management, validation | [[auth-oauth2-jwt]] |
| 11 | [[project-folder-structure]] | Project layout, modular design, API versioning structure | [[env-and-config-management]] |
| 12 | [[error-handling-and-exception-handlers]] | HTTPException, custom handlers, exception class hierarchy, logging errors | [[project-folder-structure]], [[logging]] |
| 13 | [[rate-limiting]] | Rate limiting algorithms, sliding window, Redis, tiers | [[error-handling-and-exception-handlers]], [[caching]] |
| 14 | [[caching]] | Caching strategies, Redis, HTTP caching, cache invalidation | [[rate-limiting]] |
| 15 | [[logging-and-monitoring]] | Structured logging, metrics, tracing, alerting, health checks | [[logging]], [[error-handling-and-exception-handlers]] |
| 16 | [[testing-fastapi]] | TestClient, fixtures, async testing, database testing, auth testing | [[testing-with-pytest]], [[dependency-injection]] |
| 17 | [[deployment-docker-uvicorn]] | Docker, uvicorn, gunicorn, nginx, HTTPS, process manager | [[testing-fastapi]] |
| 18 | [[websockets]] | WebSocket lifecycle, connection management, broadcasting | [[deployment-docker-uvicorn]], [[async-endpoints-when-to-use]] |
| 19 | [[streaming-responses]] | StreamingResponse, file streaming, SSE, generators | [[websockets]] |
| 20 | [[cron-and-scheduled-jobs]] | APScheduler, Celery Beat, K8s CronJob, idempotency, locking | [[background-tasks]], [[logging-and-monitoring]] |
| 21 | [[background-workers-queues]] | Celery, ARQ, brokers, dead-letter queues, retries, monitoring | [[cron-and-scheduled-jobs]], [[caching]] |
| 22 | [[inference-serving-patterns]] | Model serving, batching, GPU management, model versioning, monitoring | [[async-endpoints-when-to-use]], [[streaming-responses]] |
| 23 | [[system-design-for-apis-at-scale]] | Load balancing, scaling, database scaling, multi-region, graceful degradation | [[inference-serving-patterns]], [[rate-limiting]], [[caching]] |
| 24 | [[api-versioning]] | Versioning strategies, backward compatibility, deprecation, routing | [[system-design-for-apis-at-scale]], [[routing-and-params]] |
| 25 | [[cors-and-security-headers]] | CORS mechanics, security headers, CSRF, auth + CORS interaction | [[api-versioning]], [[middleware]], [[auth-oauth2-jwt]] |

## Cross-section links (Python ↔ FastAPI)

These files explicitly reference each other across the two sections. Don't re-read both sides — read one, follow the wikilink for context.

| Python file | FastAPI file | Connection |
|-------------|-------------|------------|
| [[async-await-and-event-loop]] | [[async-endpoints-when-to-use]] | Event loop mechanics → when to make endpoints async |
| [[concurrency-patterns]] | [[inference-serving-patterns]] | Concurrency decisions → model serving optimization |
| [[memory-management-and-gc]] | [[inference-serving-patterns]] | GPU memory management → model memory optimization |
| [[logging]] | [[logging-and-monitoring]] | Python logging → FastAPI structured logging |
| [[testing-with-pytest]] | [[testing-fastapi]] | pytest basics → FastAPI testing patterns |
| [[gil-and-threading]] | [[inference-serving-patterns]] | GIL → offloading inference to threads/processes |
| [[generators-and-iterators]] | [[streaming-responses]] | Generators → streaming response chunks |
| [[context-managers]] | [[database-integration-async-orm]] | Context managers → async DB session management |
| [[decorators]] | [[dependency-injection]] | Decorators → dependency injection patterns |
| [[exception-handling]] | [[error-handling-and-exception-handlers]] | Exception handling → FastAPI exception handlers |
| [[performance-profiling]] | [[inference-serving-patterns]] | Profiling → inference latency optimization |

## Learning plan

1. **Python phase** (~1 month): Read one Python file per day. Do the practice questions. Don't just read — write the code, break it, fix it.
2. **FastAPI phase** (~1 month): Read one FastAPI file per day. For files with cross-links to Python, review the Python side first.
3. **LeetCode phase** (ongoing): Start solving actively. Use the vault as reference when you hit a concept you need to look up. The vault is your lookup, not your primary focus during this phase.

## Conventions

- `[[wikilink]]` — link to another file in this vault. Use the filename without .md.
- `#status/new` — file is drafted, not yet reviewed. Update to `#status/reviewed` after reading.
- Code examples are runnable. Copy them, modify them, break them.
- Practice questions have collapsible callouts. Try to answer before expanding.

## Related

- [[brain.md]] — the broader learning context and personal notes
- The goal: move from "AI writes it" to "I understand why it works this way"

#status/new