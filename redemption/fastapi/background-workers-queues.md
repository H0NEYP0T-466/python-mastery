# Background Workers — Queues

## What it is
Background workers process jobs asynchronously, outside the request/response cycle. When a request needs long-running work (sending emails, processing files, ML inference, data export), the API accepts the request, queues a job, and returns immediately. A worker process picks up the job from the queue and executes it. This file covers queue architectures (Redis, RabbitMQ, SQS), worker patterns, job retries, dead-letter queues, distributed task systems (Celery, ARQ, Huey), and the distinction between background tasks (in-process) and background workers (out-of-process).

## Why it matters
Background workers are the standard pattern for decoupling request processing from long-running work. Without them, API requests time out, users wait unnecessarily, and the system can't scale workloads independently. In interviews, background worker questions test whether you understand queue semantics, at-least-once delivery, retry strategies, and distributed task orchestration. For your work — ML inference (often long-running), data processing, model training — background workers are essential for production-grade APIs.

## Core example

### Background tasks vs background workers — the critical distinction

```python
# BACKGROUND TASKS (FastAPI's BackgroundTasks)
# - Runs in the SAME process as the API
# - Runs AFTER the response is sent
# - NOT persistent — lost if process crashes
# - NOT distributed — only runs on the instance that received the request
# - Best for: quick cleanup, logging, cache invalidation (seconds)

# BACKGROUND WORKERS (Celery, ARQ, etc.)
# - Runs in SEPARATE processes/servers
# - Jobs are PERSISTED in a queue (Redis, RabbitMQ)
# - Survive process crashes and restarts
# - DISTRIBUTED — any worker can pick up any job
# - Best for: long-running work (minutes to hours), critical tasks,
#   work that must survive failures, scalable workloads

# When in doubt: if it takes more than a few seconds or MUST complete,
# use background workers. If it's quick cleanup that can be lost,
# use background tasks.
```

### Celery — the standard for Python background workers

```python
# tasks.py — Celery task definitions
from celery import Celery
from celery.exceptions import Retry

celery = Celery(
    "tasks",
    broker=REDIS_URL,  # Or "amqp://guest:guest@rabbitmq:5672//"
    backend=REDIS_URL,  # For storing results (optional)
    include=["app.tasks"],
)

# Task configuration
celery.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    
    # Retry configuration
    task_acks_late=True,  # Acknowledge after task completes (not before)
    task_reject_on_worker_lost=True,  # Requeue if worker dies mid-task
    worker_prefetch_multiplier=1,  # One task per worker at a time
    worker_concurrency=4,  # Tasks per worker process
    
    # Task time limits
    task_time_limit=3600,  # Max 1 hour per task
    task_soft_time_limit=3540,  # Soft limit (graceful shutdown)
    
    # Retry on common errors
    task_autoretry_for=(Exception,),  # Auto-retry on any exception
    task_default_retry_delay=60,  # 60 seconds between retries
    task_max_retries=3,  # Max 3 retries
)

# Task definition with retry
@celery.task(bind=True, max_retries=3, default_retry_delay=60)
def send_email_task(self, user_id: int, template: str):
    try:
        user = db.get_user(user_id)
        send_email(user.email, template)
        logger.info(f"Email sent to {user.email}")
    except smtplib.SMTPException as e:
        # Retry on transient email errors
        logger.warning(f"Email failed: {e}, retrying...")
        self.retry(exc=e)  # Exponential backoff automatically
    except Exception as e:
        # Don't retry on permanent errors
        logger.error(f"Email failed permanently: {e}")
        raise  # Task fails permanently, goes to dead-letter queue

# Task with progress tracking
@celery.task(bind=True)
def process_large_file_task(self, file_path: str):
    total = get_file_size(file_path)
    processed = 0
    
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)  # 1MB
            if not chunk:
                break
            process_chunk(chunk)
            processed += len(chunk)
            
            # Update progress (stored in backend)
            self.update_state(
                state="PROGRESS",
                meta={"current": processed, "total": total},
            )
    
    return {"status": "complete", "processed": processed}

# Calling tasks from FastAPI endpoint:
@app.post("/export/")
async def export_data(user: User = Depends(get_current_user)):
    # Queue the job — don't wait for it
    task = export_data_task.delay(user.id)
    
    # Return immediately with task ID
    return {
        "task_id": task.id,
        "status": "queued",
        "message": "Your export is being processed. Check status with the task ID.",
    }

@app.get("/export/status/{task_id}")
async def export_status(task_id: str):
    task = export_data_task.AsyncResult(task_id)
    
    return {
        "task_id": task_id,
        "status": task.state,  # PENDING, STARTED, SUCCESS, FAILURE, RETRY
        "result": task.result if task.state == "SUCCESS" else None,
        "error": str(task.info) if task.state == "FAILURE" else None,
        "progress": task.info.get("progress") if task.state == "PROGRESS" else None,
    }
```

### Celery worker deployment

```bash
# Run Celery worker (processes tasks from the queue):
$ celery -A tasks worker --loglevel=info --concurrency=4

# With multiple queues (prioritization):
$ celery -A tasks worker -Q high_priority,default,low_priority --loglevel=info

# Run Celery beat (schedules periodic tasks):
$ celery -A tasks beat --loglevel=info

# Run Flower (monitoring dashboard):
$ celery -A tasks flower --port=5566

# Docker deployment:
# Dockerfile for Celery worker (separate from FastAPI API):
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["celery", "-A", "tasks", "worker", "--loglevel=info", "--concurrency=4"]

# docker-compose.yml:
services:
  api:
    # FastAPI API
  
  worker:
    build: ./worker
    environment:
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - redis
  
  redis:
    image: redis:7-alpine
```

### Queue architecture — choosing the right broker

```python
# Redis (simplest, most common for FastAPI):
# Pros: fast, simple, in-memory, supports pub/sub,
#       widely available, good for most use cases
# Cons: data loss on restart (without persistence),
#       limited queue features (no priority queues natively)
# Best for: general-purpose task queues, caching + queue in one

# RabbitMQ (most robust):
# Pros: AMQP protocol, persistent messages, priority queues,
#       dead-letter exchanges, routing, monitoring, clustering
# Cons: more complex to set up and operate, Erlang-based
# Best for: production systems requiring guaranteed delivery,
#       complex routing, message priority

# AWS SQS (managed, cloud-native):
# Pros: fully managed, scalable, integrated with AWS,
#       dead-letter queues, visibility timeout
# Cons: AWS-only, eventual consistency, cost at scale
# Best for: AWS deployments, serverless architectures

# Comparison for FastAPI:
# Development: Redis (simple, single instance for cache + queue)
# Production: RabbitMQ (robust, guaranteed delivery) or Redis (if already using it)
# Cloud: SQS (if on AWS) or Redis Cloud / Amazon ElastiCache
```

### Dead-letter queue — handling failed jobs

```python
# When a task fails after all retries, it goes to a dead-letter queue (DLQ).
# The DLQ holds failed tasks for inspection and manual reprocessing.

# Celery + Redis DLQ configuration:
# Celery doesn't have built-in DLQ for Redis broker.
# Use a custom task base class:

from celery import Task
from celery.exceptions import Reject

class DLQTask(Task):
    """Task base class with dead-letter queue support"""
    
    def on_failure(self, exc, task_id, args, kwargs, einfo):
        # Called when task fails after all retries
        # Send to DLQ
        dlq_data = {
            "task_id": task_id,
            "task_name": self.name,
            "args": args,
            "kwargs": kwargs,
            "error": str(exc),
            "traceback": str(einfo),
            "timestamp": datetime.utcnow().isoformat(),
        }
        redis_client.lpush("dlq:tasks", json.dumps(dlq_data))
        logger.error(f"Task {task_id} failed and sent to DLQ: {exc}")

# Apply to all tasks:
@celery.task(base=DLQTask, bind=True, max_retries=3)
def my_task(self, data):
    ...

# DLQ inspection endpoint (FastAPI):
@app.get("/admin/dlq/")
async def inspect_dlq(admin: User = Depends(get_admin_user)):
    # Get last 100 failed tasks from DLQ
    tasks = redis_client.lrange("dlq:tasks", 0, 99)
    return [json.loads(t) for t in tasks]

# DLQ reprocessing endpoint:
@app.post("/admin/dlq/retry/{task_id}")
async def retry_dlq_task(task_id: str, admin: User = Depends(get_admin_user)):
    # Find the task in DLQ and re-queue it
    dlq_tasks = redis_client.lrange("dlq:tasks", 0, -1)
    for task_data in dlq_tasks:
        task = json.loads(task_data)
        if task["task_id"] == task_id:
            # Re-queue the original task
            task_name = task["task_name"]
            args = task["args"]
            kwargs = task["kwargs"]
            
            # Get the task by name and apply
            celery.tasks[task_name].apply_async(args=args, kwargs=kwargs)
            
            # Remove from DLQ
            redis_client.lrem("dlq:tasks", 0, task_data)
            
            return {"status": "retried", "task_id": task_id}
    
    raise HTTPException(404, "Task not found in DLQ")

# For RabbitMQ, DLQ is built-in:
# Configure a dead-letter exchange on the main queue.
# Failed messages are automatically routed to the DLQ.
# Inspect via RabbitMQ management UI or API.
```

### Rate limiting and prioritization in queues

```python
# Rate limiting — control how many tasks run per second
@celery.task(rate_limit="10/m")  # Max 10 per minute
def send_email_task(user_id: int):
    # This task is rate-limited to 10 executions per minute
    # Useful for: email sending (provider limits), API calls (rate limits)
    ...

# Rate limits can be per-task or global:
# "10/m" = 10 per minute
# "100/h" = 100 per hour
# "5/s" = 5 per second

# Priority queues — process important tasks first
# Celery supports priority queues with RabbitMQ broker:
# celery.conf.task_queues = (
#     Queue("high_priority", priority=10),
#     Queue("default", priority=5),
#     Queue("low_priority", priority=1),
# )

# Send task to specific queue:
# send_email_task.apply_async(queue="high_priority")
# process_data_task.apply_async(queue="default")
# cleanup_task.apply_async(queue="low_priority")

# Workers consume from specific queues:
# $ celery -A tasks worker -Q high_priority,default --loglevel=info
# This worker only processes high_priority and default queues.

# For Redis (no native priority), use separate queues and
# have workers check high-priority queue first:
# custom worker logic that polls high_priority before default

# Prioritization use cases:
# - VIP users → high priority queue
# - Payment processing → high priority queue
# - Data export → low priority queue
# - Model training → dedicated queue with dedicated workers
```

### Distributed task orchestration — complex workflows

```python
# For complex workflows (task A → task B → task C, or fan-out/fan-in),
# use Celery canvas (workflow primitives).

from celery import chain, group, chord, chunks

# Chain: task A → task B → task C (sequential, output of A is input of B)
workflow = chain(
    fetch_data.s(url),
    process_data.s(),
    save_results.s(),
)
result = workflow.delay()  # Runs: fetch → process → save

# Group: run multiple tasks in parallel (fan-out)
urls = ["url1", "url2", "url3", "url4"]
workflow = group(fetch_data.s(url) for url in urls)
result = workflow.delay()  # Runs all 4 fetches in parallel
# result.get() returns list of results

# Chord: group + callback (fan-out then fan-in)
urls = ["url1", "url2", "url3"]
workflow = chord(
    group(fetch_data.s(url) for url in urls),  # Header (fan-out)
    aggregate_results.s()  # Body (callback, runs after all header tasks)
)
result = workflow.delay()  # Fetch all 3, then aggregate

# Chunks: split a large task into smaller chunks
large_list = list(range(10000))
workflow = chunks(process_item.s(), large_list, 100)  # 100 chunks of 100 items
result = workflow.delay()  # Process 100 chunks in parallel

# For ML pipelines:
# Chain: preprocess → inference → postprocess → save
# Group: process multiple inputs in parallel
# Chord: process batch → aggregate results → store
# Chunks: split large dataset into batches for parallel processing

# Alternative: use Prefect or Airflow for complex workflows.
# Celery canvas is good for simple workflows. Prefect/Airflow are
# better for complex DAGs with dependencies, scheduling, and monitoring.
```

### Job monitoring and observability

```python
# Monitor Celery workers and tasks:

# 1. Flower (web dashboard)
# $ celery -A tasks flower --port=5566
# Access: http://localhost:5566
# Features: task history, worker status, broker monitoring,
#           task retry, revoke, rate limiting

# 2. Prometheus metrics (celery-exporter)
# celery-exporter exposes Prometheus metrics:
# - celery_task_sent_total
# - celery_task_success_total
# - celery_task_failure_total
# - celery_task_runtime
# - celery_worker_up
# Scrape with Prometheus, visualize in Grafana.

# 3. Custom task signals for logging
from celery import signals

@signals.task_success.connect
def task_success(sender=None, result=None, **kwargs):
    logger.info(
        f"Task {sender.name}[{kwargs['task_id']}] succeeded "
        f"in {kwargs['runtime']:.2f}s"
    )

@signals.task_failure.connect
def task_failure(sender=None, exception=None, traceback=None, **kwargs):
    logger.error(
        f"Task {sender.name}[{kwargs['task_id']}] failed: "
        f"{exception}"
    )

@signals.task_retry.connect
def task_retry(sender=None, request=None, reason=None, **kwargs):
    logger.warning(
        f"Task {sender.name}[{request.id}] retrying: {reason}"
    )

# 4. Task duration tracking
@signals.before_task_publish.connect
def task_publish(sender=None, body=None, **kwargs):
    # Record when task is published
    redis_client.set(f"task:published:{body['id']}", time.time())

@signals.task_success.connect
def track_duration(sender=None, result=None, **kwargs):
    task_id = kwargs["task_id"]
    published = redis_client.get(f"task:published:{task_id}")
    if published:
        duration = time.time() - float(published)
        logger.info(f"Task {task_id} completed in {duration:.2f}s")
        # Also send to Prometheus histogram
        task_duration.observe(duration)

# 5. Health check for workers
@app.get("/health/workers/")
async def check_workers():
    # Check if Celery workers are alive
    try:
        # Ping all workers
        response = celery.control.ping(timeout=5)
        return {
            "status": "healthy",
            "workers": len(response) if response else 0,
            "details": response,
        }
    except Exception as e:
        raise HTTPException(503, f"Worker health check failed: {e}")
```

## Common mistakes / gotchas

- **Not acknowledging tasks properly** — with `task_acks_late=True`, the task is acknowledged after completion. If the worker crashes mid-task, the task is requeued. Without it, the task is acknowledged when received — if the worker crashes, the task is lost. Always use `task_acks_late=True` for critical tasks.
- **Worker running out of memory** — long-running workers accumulate memory (Python memory leaks, cached data). Use `worker_max_tasks_per_child=N` to restart workers after N tasks, clearing memory. Set to 100-1000 depending on task memory usage.
- **Not handling task serialization** — Celery serializes task arguments. Complex Python objects (datetime, custom classes) may not serialize correctly. Use JSON serializer and pass simple types (IDs, strings, numbers). Fetch complex objects inside the task.
- **Tasks that depend on request context** — a task running in a worker doesn't have access to the FastAPI request context (current user, request state). Pass all needed data as task arguments. Don't rely on global state.
- **Infinite retry loops** — if a task always fails and has no max_retries, it retries forever. Always set `max_retries` and use exponential backoff. After max retries, the task goes to the dead-letter queue.
- **Using the same Redis for cache and queue without separation** — if Redis fills up with queue data, cache entries are evicted. Use separate Redis databases (different DB number) or separate Redis instances for cache and queue.
- **Not monitoring queue depth** — if tasks are produced faster than they're consumed, the queue grows. Set up alerts on queue depth. If queue depth is increasing, add more workers or optimize task execution time.
- **Tasks that are too large** — Celery stores task arguments in the broker. Large arguments (e.g., sending a 10MB file as a task argument) bloat the broker. Pass file paths or IDs, not the data itself.

## Practice

> [!question]- Q1. Design a background worker system for a FastAPI ML inference API with: (1) synchronous inference for real-time requests (2) asynchronous inference for batch jobs (3) model retraining jobs (4) result cleanup. Show the queue architecture, worker configuration, and endpoint design.
**Answer:** 
- **Queue architecture**: Use Redis as broker. Four queues: `realtime` (synchronous inference, high priority), `batch` (asynchronous batch jobs, normal priority), `training` (model retraining, low priority, dedicated workers), `cleanup` (result cleanup, lowest priority). Each queue has its own worker configuration.
- **Workers**: `realtime` workers (4 per instance, low latency, short timeout), `batch` workers (8 per instance, higher concurrency), `training` workers (2 dedicated instances, GPU, long timeout), `cleanup` workers (1 per instance, scheduled). Each worker type has appropriate concurrency and time limits.
- **Endpoints**: POST /v1/predict/ → synchronous inference (realtime queue, wait for result or timeout). POST /v1/predict/batch/ → queue batch job (batch queue, return task ID). POST /v1/models/retrain/ → queue training job (training queue, return task ID). GET /v1/tasks/{id} → check task status.
- **Retry strategy**: realtime tasks: no retry (fail fast, client retries). batch tasks: retry 3 times with exponential backoff. training tasks: retry 2 times (expensive). cleanup tasks: retry 5 times (non-critical). All failed tasks go to DLQ for inspection.
- **Scaling**: realtime workers autoscale based on request latency. batch workers autoscale based on queue depth. training workers are fixed (GPU-limited). cleanup workers run on schedule. The key design: separate queues for different workload characteristics, appropriate worker configuration per queue, task-specific retry strategies, monitoring for queue depth and worker health.

> [!question]- Q2. A Celery worker processing ML inference tasks occasionally loses tasks — the task is sent to the queue but never executed. Diagnose and fix.
**Answer:** Possible causes: (1) **Task acknowledgment before execution** — if `task_acks_late=False` (default), the task is acknowledged when received by the worker. If the worker crashes before completing the task, the task is lost. Fix: set `task_acks_late=True` so the task is acknowledged after completion. (2) **Worker timeout** — if the task takes longer than `task_time_limit`, the worker kills the task. If `task_reject_on_worker_lost=False`, the task is not requeued. Fix: set `task_reject_on_worker_lost=True` and increase `task_time_limit`. (3) **Redis persistence** — if Redis restarts without persistence, unprocessed tasks are lost. Fix: enable Redis RDB/AOF persistence or use RabbitMQ (persistent messages). (4) **Worker not consuming** — the worker is running but not consuming from the right queue. Fix: check worker queue configuration (`-Q` parameter). (5) **Task serialization error** — the task arguments can't be deserialized. The worker silently drops the task. Fix: check worker logs for deserialization errors, ensure task arguments are JSON-serializable. Diagnosis: check worker logs for errors. Check Redis for unprocessed tasks (`llen celery`). Check if workers are consuming (`celery inspect active`). Test with a simple task. The most common cause: `task_acks_late=False` with worker crashes. Fix: `task_acks_late=True` + `task_reject_on_worker_lost=True`.

> [!question]- Q3. Compare Celery, ARQ, and Huey for FastAPI background workers. When would you choose each?
**Answer:** Celery: mature, feature-rich, supports multiple brokers (Redis, RabbitMQ, SQS), has monitoring (Flower), workflows (canvas), periodic tasks (Beat), and a large ecosystem. Pros: battle-tested, most features, best for production. Cons: complex configuration, synchronous task API (async workers need extra setup), heavier. Best for: production systems with diverse task types, complex workflows, periodic tasks, monitoring requirements. ARQ: async-first, designed for asyncio, simple API, Redis-only, built-in retry and job management. Pros: native async support, simple, lightweight, good for FastAPI (same async ecosystem). Cons: Redis-only, fewer features, smaller ecosystem, no built-in UI. Best for: async FastAPI apps, simple to moderate background tasks, when you want async workers that match your app's async style. Huey: simple, supports multiple brokers (Redis, RabbitMQ, SQLite), lightweight, has periodic tasks. Pros: simple API, multiple brokers, periodic tasks, smaller than Celery. Cons: less feature-rich than Celery, smaller community, no async support. Best for: simple background tasks, when you want something lighter than Celery but more features than a raw queue. Recommendation: for new FastAPI projects with async code, ARQ is the natural fit (async workers match the app). For complex workflows, periodic tasks, and production-grade monitoring, Celery is the safer choice. For simple needs with minimal setup, Huey works. Start with ARQ for async FastAPI, migrate to Celery if you need more features.

> [!question]- Q4. Your FastAPI API queues a background job that takes 5 minutes. The client wants to know the progress. Design the solution so the client can check progress and receive the final result.
**Answer:** Pattern: task ID + progress tracking + result storage. (1) Endpoint queues the job and returns a task_id immediately. (2) The background worker updates progress in Redis (or database) using `task.update_state(state="PROGRESS", meta={"progress": 50})`. (3) Client polls GET /tasks/{task_id} to check progress — returns state (PENDING, STARTED, PROGRESS, SUCCESS, FAILURE) and progress percentage. (4) When complete, the worker stores the result in Redis/database with a TTL (e.g., 24 hours). (5) Client retrieves result from the same endpoint when state is SUCCESS. (6) For real-time updates, add WebSocket: when the worker updates progress, push to the client via WebSocket (using task_id to route). (7) For push notifications, send a webhook or email when the task completes. Implementation: Celery with Redis backend. The task updates state periodically. The status endpoint reads from Celery's result backend. For WebSocket: the worker publishes progress to Redis Pub/Sub; a FastAPI background task listens and pushes to connected clients. Key design: task_id as the correlation key, progress stored in a shared store (Redis), client pulls or pushes for updates, result stored with TTL for cleanup.

> [!question]- Q5. A background worker processes image uploads. The queue has 10,000 pending tasks. A new high-priority task (VIP user upload) is queued but has to wait behind all 10,000 tasks. Design a solution so high-priority tasks are processed immediately.
**Answer:** Use priority queues. Create two queues: `high_priority` and `default`. High-priority tasks (VIP users, urgent processing) go to `high_priority` queue. Regular tasks go to `default` queue. Workers consume from `high_priority` first, then `default`. Configuration: (1) RabbitMQ: use priority queues (x-max-priority=10). Tasks with higher priority are dequeued first. (2) Redis: no native priority, but use separate queues and have workers check high_priority first. (3) Celery: define multiple queues with different priorities. Workers consume from high_priority queue first. Implementation: in the endpoint, check user tier — VIP users get `task.apply_async(queue="high_priority")`, regular users get `task.apply_async(queue="default")`. Workers: `celery -A tasks worker -Q high_priority,default`. The worker processes high_priority tasks first. If high_priority is empty, it processes default. For 10,000 pending tasks in default and 1 new high_priority task: the worker finishes the current task (if any), then checks high_priority, processes the VIP task immediately, then returns to default. The VIP task doesn't wait behind 10,000 tasks. Key design: separate queues by priority, workers consume from high-priority first, task routing based on user/urgency. For production: add a third queue for low-priority (background cleanup) to ensure high-priority tasks are never blocked.

## Related
[[background-tasks]]
[[cron-and-scheduled-jobs]]
[[caching]]
[[rate-limiting]]
[[inference-serving-patterns]]
[[logging-and-monitoring]]

#status/new