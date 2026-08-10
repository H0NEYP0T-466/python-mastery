# Logging

## What it is
Python's `logging` module is a hierarchical, configurable logging system — far more powerful than `print()` statements. It separates log production (what you log) from log consumption (where it goes and in what form) through loggers, handlers, formatters, and filters. The hierarchy (by logger name) allows fine-grained control over log levels per module. But the logging module is also notoriously easy to misconfigure — leading to silent failures (no logs appear), duplicate logs, or logs going nowhere. This file covers the architecture, correct configuration patterns, structured logging, and the common pitfalls that make people give up on logging and go back to `print()`.

## Why it matters
In production, `print()` is useless — it goes to stdout with no levels, no structure, no rotation, and no filtering. Logging is the standard for production observability. But misconfigured logging is worse than no logging: it gives false confidence ("we have logging") while silently dropping critical errors. In interviews, logging questions test whether you understand the hierarchy, propagation, and the difference between root and named loggers. For your FastAPI work — proper logging is non-negotiable for debugging production issues, monitoring request latency, and tracing errors across services.

## Core example

### The logging architecture — four components

```python
import logging

# 1. Logger — the entry point. You get a logger by name.
#    Loggers are hierarchical: 'app' is the parent of 'app.db', 'app.api', etc.
logger = logging.getLogger("myapp")  # Named logger
# logger = logging.getLogger()      # Root logger (no name)

# 2. Handler — determines WHERE logs go (console, file, network, etc.)
console_handler = logging.StreamHandler()          # stdout/stderr
file_handler = logging.FileHandler("app.log")      # File
rotating_handler = logging.RotatingFileHandler(    # Rotating file
    "app.log", maxBytes=10*1024*1024, backupCount=5
)

# 3. Formatter — determines HOW logs look (text, JSON, etc.)
formatter = logging.Formatter(
    "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
# asctime: timestamp
# name: logger name
#levelname: DEBUG, INFO, WARNING, ERROR, CRITICAL
# message: the log message
# Also: %(filename)s, %(lineno)s, %(funcName)s, %(thread)d

# 4. Filter — determines WHICH logs pass through (beyond level-based)
# Rarely used directly, but available for custom filtering logic.

# Wiring it together:
logger.setLevel(logging.INFO)  # Logger level — what this logger emits
console_handler.setLevel(logging.DEBUG)  # Handler level — what this handler shows
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# Now:
logger.debug("won't show — logger level is INFO")
logger.info("will show — INFO >= INFO")
logger.error("will show — ERROR >= INFO")
```

### Logger hierarchy and propagation

```python
import logging

# Loggers form a tree based on dot-separated names:
# root (no name)
# └── myapp
#     ├── myapp.db
#     ├── myapp.api
#     └── myapp.api.auth

# By default, log messages propagate UP the hierarchy. A log from
# myapp.api.auth goes to: myapp.api.auth logger → myapp.api logger
# → myapp logger → root logger. Each logger's handlers process it.

# This means: if root has a StreamHandler, ALL logs from ALL loggers
# go to stdout — even if you didn't explicitly configure child loggers.

# To stop propagation (prevent parent handlers from seeing the log):
logger = logging.getLogger("myapp.api.auth")
logger.propagate = False  # Only this logger's handlers see the log

# Practical example:
# Root logger: FileHandler (all logs to file)
# myapp.api logger: StreamHandler (API logs also to console)
# myapp.api.auth logger: propagate=False (auth logs only to its own handlers,
#   not to root's file handler — useful for sensitive logs you don't want
#   in the general log file)

# The hierarchy enables fine-grained control:
# Set log levels per module:
logging.getLogger("myapp.db").setLevel(logging.DEBUG)   # DB queries → verbose
logging.getLogger("myapp.api").setLevel(logging.INFO)   # API → normal
logging.getLogger("myapp.api.auth").setLevel(logging.WARNING)  # Auth → only warnings+
```

### The correct way to configure logging — once, at startup

```python
import logging
import logging.config

# DON'T do this in every module:
# logger = logging.getLogger("myapp")
# logger.addHandler(logging.StreamHandler())  # Multiple handlers!
# This creates duplicate handlers every time the module is imported.

# DO configure once at application startup:

# Approach 1: dictConfig (recommended for most apps)
LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,  # Keep loggers from imported modules
    "formatters": {
        "standard": {
            "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        },
        "json": {
            "()": "pythonjsonlogger.jsonlogger.JsonFormatter",  # Third-party
            "format": "%(asctime)s %(name)s %(levelname)s %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
            "level": "DEBUG",
        },
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": "app.log",
            "maxBytes": 10 * 1024 * 1024,  # 10MB
            "backupCount": 5,
            "formatter": "standard",
            "level": "INFO",
        },
    },
    "loggers": {
        "myapp": {
            "handlers": ["console", "file"],
            "level": "INFO",
            "propagate": False,  # Don't propagate to root (avoid duplicates)
        },
        "uvicorn.access": {  # Suppress noisy access logs
            "handlers": [],
            "level": "WARNING",
            "propagate": False,
        },
    },
    "root": {  # Root logger — catches everything not handled above
        "handlers": ["console"],
        "level": "WARNING",
    },
}

logging.config.dictConfig(LOGGING_CONFIG)

# Now, in any module:
# logger = logging.getLogger(__name__)  # Uses module's dotted path as logger name
# logger.info("request processed")  # Goes to console + file (via myapp logger)

# The key: configure ONCE at startup. Use dictConfig for complex setups.
# Use getLogger(__name__) in modules — the logger name matches the module,
# enabling per-module log level control.
```

### Structured logging — JSON logs for production

```python
# Plain text logs are fine for local development. For production,
# structured logs (JSON) are essential — they can be parsed by log
# aggregation tools (ELK, Datadog, Splunk) and queried efficiently.

# Using python-json-logger (pip install python-json-logger):
import logging
from pythonjsonlogger import jsonlogger

logger = logging.getLogger("myapp")
handler = logging.StreamHandler()
formatter = jsonlogger.JsonFormatter(
    "%(asctime)s %(name)s %(levelname)s %(message)s %(request_id)s"
)
handler.setFormatter(formatter)
logger.addHandler(handler)

# To include structured fields (request_id, user_id, etc.):
# Use LoggerAdapter to inject context:
class ContextFilter(logging.Filter):
    def __init__(self):
        self.context = {}
    
    def filter(self, record):
        # Add context fields to every log record
        for key, value in self.context.items():
            setattr(record, key, value)
        return True
    
    def set_context(self, key, value):
        self.context[key] = value

filter = ContextFilter()
logger.addFilter(filter)

# Per-request context (for web apps):
# In middleware:
filter.set_context("request_id", request.id)
filter.set_context("user_id", request.user.id)
logger.info("request started")  # Includes request_id and user_id in JSON
# After request:
filter.set_context("request_id", None)  # Clear

# This enables tracing: all logs for a request share the same request_id,
# making it easy to filter and trace a request's full journey through
# the system. This is the standard pattern for distributed tracing in
# microservices.
```

### Logging in async code — the gotcha

```python
import logging
import asyncio

# The logging module is synchronous and thread-safe. In async code,
# calling logger.info() blocks the event loop if the handler is slow
# (e.g., writing to a file or network).

# For most cases, this is fine — logging is fast enough that the
# brief block doesn't matter. But for high-throughput async services,
# you need async logging.

# Option 1: Use a QueueHandler + QueueListener (built-in, offloads to thread)
import logging.handlers

log_queue = logging.handlers.Queue(-1)  # Unbounded queue
queue_handler = logging.handlers.QueueHandler(log_queue)

# Root logger uses the queue handler (non-blocking)
logging.getLogger().addHandler(queue_handler)

# A separate listener thread reads from the queue and dispatches to handlers
listener = logging.handlers.QueueListener(
    log_queue,
    logging.StreamHandler(),  # All real handlers go here
    respect_handler_level=True,
)
listener.start()

# Now logger.info() is non-blocking — it just puts on the queue.
# The listener thread handles the actual I/O.
# Don't forget to stop the listener on shutdown:
# listener.stop()

# Option 2: Use an async logging library (aiologger, structlog with async)
# These provide async logger methods but are less mature than the
# standard library's QueueHandler approach.

# For FastAPI: the QueueHandler approach is recommended. It's built-in,
# well-tested, and doesn't require third-party dependencies. The queue
# provides backpressure — if the listener can't keep up, the queue grows,
# but the request handler isn't blocked. In extreme cases, you can use
# a bounded queue to apply backpressure (drop logs instead of OOM).
```

### Log levels — when to use each

```python
import logging

# DEBUG — Detailed information, typically of interest only when
# diagnosing problems. Variable values, function entry/exit, SQL queries.
# Only enabled in development or when specifically requested.
logger.debug(f"User {user_id} loaded from cache: {user}")

# INFO — Confirmation that things are working as expected. Request
# completed, server started, job finished. The default production level.
logger.info(f"Request {request_id} completed in {duration_ms}ms")

# WARNING — Something unexpected happened, or a potential problem,
# but the application continues. Deprecated API usage, low disk space,
# retrying a failed operation.
logger.warning(f"Cache miss for key {key} — falling back to database")

# ERROR — A more serious problem — the function couldn't complete its
# task. Exception caught but handled. Database connection failed but
# we have a fallback.
logger.error(f"Failed to process order {order_id}", exc_info=True)

# CRITICAL — A very serious error — the application may be unable to
# continue. Database down, disk full, out of memory.
logger.critical("Database connection lost — shutting down")

# exc_info=True — includes the exception traceback in the log.
# Always use for ERROR and CRITICAL logs that are exception-related.

# Practical guidelines:
# - Don't log sensitive data (passwords, tokens, PII) at any level
# - Log request IDs for traceability
# - Log durations for performance monitoring
# - Use structured fields (not string formatting) for queryable data
# - Don't log at DEBUG in production — it's too verbose and can
#   expose sensitive information or degrade performance
```

## Common mistakes / gotchas

- **Not configuring logging at all** — relying on the default root logger, which only shows WARNING and above to stderr. You miss INFO and DEBUG logs entirely. Always configure explicitly.
- **Configuring logging in every module** — calling `logger.addHandler()` in multiple modules creates duplicate handlers. Each import adds another handler, so logs appear multiple times. Configure once at startup using `dictConfig` or `fileConfig`.
- **Forgetting `disable_existing_loggers=False`** — `dictConfig` by default disables loggers that existed before the config was applied. This breaks logging from libraries that created loggers during import. Always set `disable_existing_loggers: False` unless you explicitly want to silence existing loggers.
- **Using `print()` in production code** — print goes to stdout with no levels, no structure, no filtering, no rotation. It can't be controlled at runtime. Use logging for anything that might need to be observed in production.
- **Logging at the wrong level** — logging recoverable conditions as ERROR (causing false alarms) or serious conditions as INFO (missing them in monitoring). Use the severity guidelines: DEBUG for dev, INFO for normal operations, WARNING for unexpected but handled, ERROR for failures, CRITICAL for system-threatening issues.
- **Not including context in logs** — a log saying "request failed" without request_id, user_id, or endpoint is useless for debugging. Always include identifiers that let you trace the request. Use LoggerAdapter or structlog for structured context.
- **Synchronous logging blocking async handlers** — in high-throughput async services, file/network logging can block the event loop. Use QueueHandler + QueueListener to offload logging to a thread.
- **Leaving DEBUG level in production** — DEBUG logs can expose sensitive data (tokens, user data, internal state) and degrade performance due to volume. Never run production at DEBUG level. Use a dynamic log level switch (e.g., via admin endpoint) for temporary debugging.

## Practice

> [!question]- Q1. Design a logging configuration for a FastAPI application running in production with the following requirements: (1) JSON format for log aggregation, (2) request_id in every log within a request, (3) different log levels for different modules, (4) log rotation (10MB, 5 backups), (5) async-safe (don't block the event loop).
**Answer:**
```python
import logging
import logging.config
import logging.handlers
from pythonjsonlogger import jsonlogger

LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "()": jsonlogger.JsonFormatter,
            "format": "%(asctime)s %(name)s %(levelname)s %(request_id)s %(message)s",
        },
    },
    "handlers": {
        "queue": {
            "class": "logging.handlers.QueueHandler",
            "queue": logging.handlers.Queue(-1),  # Unbounded
        },
    },
    "loggers": {
        "myapp": {
            "handlers": ["queue"],
            "level": "INFO",
            "propagate": False,
        },
        "myapp.db": {"level": "DEBUG"},  # More verbose for DB
        "myapp.api.auth": {"level": "WARNING"},  # Less verbose for auth
    },
    "root": {"handlers": ["queue"], "level": "WARNING"},
}

logging.config.dictConfig(LOGGING_CONFIG)

# Start the listener thread (after dictConfig)
queue = list(logging.Logger.manager.loggerDict.values())
# Actually, get the queue from the handler:
root = logging.getLogger()
for h in root.handlers:
    if isinstance(h, logging.handlers.QueueHandler):
        listener = logging.handlers.QueueListener(
            h.queue,
            logging.StreamHandler(),  # Or FileHandler with rotation
            jsonlogger.JsonFormatter(...),
            respect_handler_level=True,
        )
        listener.start()
        break

# For request context — middleware that sets request_id:
class LoggingMiddleware:
    def __init__(self, app):
        self.app = app
    
    async def __call__(self, scope, receive, send):
        request_id = generate_id()
        # Set in thread-local or contextvar for the filter
        context.set("request_id", request_id)
        try:
            await self.app(scope, receive, send)
        finally:
            context.set("request_id", None)
```
The architecture: QueueHandler for non-blocking logging (put on queue, return immediately), QueueListener thread for actual JSON formatting and output, per-module log levels for granular control, JSON formatter for log aggregation, and request context injection via middleware. The queue provides backpressure — if the listener can't keep up, the queue grows but requests aren't blocked. For production, you'd also add a bounded queue (with overflow handling) and a shutdown hook to stop the listener.

> [!question]- Q2. Explain why this code produces duplicate log messages and fix it:
```python
# module.py
import logging
logger = logging.getLogger("myapp")
logger.addHandler(logging.StreamHandler())
logger.setLevel(logging.INFO)

def do_something():
    logger.info("doing something")
```
**Answer:** If `module.py` is imported multiple times (or if the logger configuration code runs multiple times), each import adds a new StreamHandler to the logger. Since log messages propagate to all handlers, the same log message appears multiple times — once per handler. Additionally, if the root logger also has a StreamHandler, the message appears there too (propagation). Fix: (1) Move logging configuration to a single `setup_logging()` function called once at application startup. (2) In modules, only do `logger = logging.getLogger(__name__)` — no handler setup. (3) Use `logger.handlers.clear()` before adding handlers if you must configure programmatically (but better to use `dictConfig`). (4) Set `propagate = False` on named loggers if you don't want root logger handlers to also process the message. The standard pattern: configure once at startup with `dictConfig`, use `getLogger(__name__)` in modules with no handler setup.

> [!question]- Q3. You're running a long-running data processing job that produces millions of log lines. The log file grows to hundreds of GB, making it useless. Design a logging strategy that keeps logs manageable while preserving the ability to debug failures.
**Answer:** Three-pronged strategy: (1) **Log rotation** — use `RotatingFileHandler` or `TimedRotatingFileHandler` with size-based (10MB) or time-based (daily) rotation. Keep 5-10 backups. Old logs are compressed and archived. (2) **Sampling** — don't log every item processed. Log at INFO level periodically (every 1000 items) or at summary intervals (batch completion). Use DEBUG for per-item logging, which is disabled in production. (3) **Structured logging with levels** — log failures and errors at ERROR level with full context (item ID, error type, traceback). Log progress at INFO level with aggregate metrics (items processed, rate, ETA). Use a separate error log file that only captures ERROR and above — this file stays small and contains all the important debugging information. For debugging specific failures, enable DEBUG logging temporarily via a runtime flag (e.g., an admin endpoint that changes log level) for the specific component or item ID. This avoids the "log everything forever" approach while ensuring critical information is always captured.

> [!question]- Q4. What is the difference between `logger.setLevel()`, `handler.setLevel()`, and `filter()`? In what order are they evaluated for a log message?
**Answer:** `logger.setLevel()` sets the minimum level for the logger — messages below this level are not processed by the logger at all. `handler.setLevel()` sets the minimum level for a specific handler — a message may pass the logger level but be filtered by a handler level. `filter()` is a custom function that can implement arbitrary filtering logic beyond level-based filtering (e.g., filter by message content, logger name, or custom attributes). Evaluation order for a log message: (1) Logger level check — if message level < logger level, discard. (2) Filter check on logger — if filter returns False, discard. (3) Propagation — message is passed to parent loggers (if propagate=True). (4) For each handler: handler level check — if message level < handler level, skip this handler. (5) Filter check on handler — if filter returns False, skip this handler. (6) Formatter formats the message. (7) Handler emits the formatted message. This means a message can be at INFO level, pass the logger (set to INFO), but be suppressed by a handler set to WARNING — the message goes to some handlers but not others. The filter provides the finest-grained control, evaluated last before emission.

> [!question]- Q5. Explain the difference between `logging.getLogger(__name__)` and `logging.getLogger("myapp")` in a module `myapp/submodule.py`. When would you use each?
**Answer:** In `myapp/submodule.py`, `__name__` is `"myapp.submodule"`. So `getLogger(__name__)` creates a logger named `"myapp.submodule"`, while `getLogger("myapp")` creates (or retrieves) the logger named `"myapp"`. The `"myapp.submodule"` logger is a child of `"myapp"` in the hierarchy — it inherits handlers and level from `"myapp"` unless explicitly overridden. Using `getLogger(__name__)` is the standard practice — it gives you per-module loggers that can be configured independently (e.g., set `myapp.submodule` to DEBUG while keeping `myapp` at INFO). Using `getLogger("myapp")` in every module means all modules share the same logger — you lose per-module control. The `__name__` approach is recommended because it enables the hierarchical configuration that makes logging powerful: you can set different levels for different modules, add module-specific handlers, and control propagation. The only reason to use a shared logger name is if you genuinely want all modules to share the same logging configuration with no differentiation.

## Related
[[context-managers]]
[[exception-handling]]
[[env-and-config-management]]
[[logging-and-monitoring]]

#status/new