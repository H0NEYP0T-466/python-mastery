# Cron and Scheduled Jobs

## What it is
Scheduled jobs (cron jobs) let you run code at specific times or intervals without external triggers. In FastAPI, this means running periodic tasks: cleanup jobs, data aggregation, report generation, cache warming, model retraining, and health checks. This file covers the approaches (APScheduler, Celery Beat, Hermes cron, OS cron), the trade-offs of each, and the patterns for reliable scheduled execution in distributed systems.

## Why it matters
Every production system needs scheduled tasks. But running them incorrectly causes duplicate executions (multiple instances running the same job), missed executions (job skipped during deployment), and resource contention (job runs during peak traffic). In interviews, scheduled job questions test whether you understand distributed cron, idempotency, and the difference between process-level and system-level scheduling. For your work — periodic model evaluation, cache refresh, data export — scheduled jobs are essential.

## Core example

### The approaches — comparison

```python
# 1. APScheduler (in-process, Python-native)
# Pros: pure Python, easy to set up, supports multiple triggers
# Cons: runs in the same process as the API, not distributed-safe
#       (multiple instances all run the job), lost on restart
# Best for: single-instance deployments, development, simple tasks

# 2. Celery Beat + Celery workers (distributed, message-queue based)
# Pros: distributed-safe (one worker executes), persistent (tasks
#       survive restarts), scalable, monitored
# Cons: requires Redis/RabbitMQ, adds infrastructure complexity
# Best for: production, distributed systems, critical scheduled tasks

# 3. OS cron + script (system-level, external)
# Pros: simple, reliable, independent of app process
# Cons: no integration with app code, hard to pass app context,
#       no monitoring, no retry logic
# Best for: simple system-level tasks (log rotation, backup)

# 4. Hermes cron (built-in, for Hermes agents)
# Pros: integrated with Hermes, supports skills, deliver to channels
# Cons: specific to Hermes ecosystem
# Best for: Hermes-based scheduled tasks, notifications, reminders

# 5. Kubernetes CronJob (orchestration-level)
# Pros: distributed-safe (one pod runs), integrated with K8s,
#       resource-managed, monitored
# Cons: K8s-specific, requires container image
# Best for: K8s deployments, batch jobs, data processing
```

### APScheduler — simple in-process scheduling

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from contextlib import asynccontextmanager
from fast import FastAPI

scheduler = AsyncIOScheduler()

# Scheduled job — runs every hour
@scheduler.scheduled_job(CronTrigger(hour="*/1"))
async def hourly_cleanup():
    await cleanup_old_sessions()
    await flush_expired_cache()
    logger.info("Hourly cleanup completed")

# Scheduled job — runs every 30 minutes
@scheduler.scheduled_job(IntervalTrigger(minutes=30))
async def refresh_metrics():
    await update_dashboard_metrics()
    logger.info("Metrics refreshed")

# Scheduled job — runs daily at 2 AM
@scheduler.scheduled_job(CronTrigger(hour=2, minute=0))
async def daily_report():
    await generate_daily_report()
    await send_reports()
    logger.info("Daily report generated")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start scheduler on startup
    scheduler.start()
    yield
    # Shutdown scheduler on shutdown
    scheduler.shutdown()

app = FastAPI(lifespan=lifespan)

# APScheduler trigger types:
# CronTrigger: cron-style (minute, hour, day, month, day_of_week)
# IntervalTrigger: every N seconds/minutes/hours/days
# DateTrigger: run once at a specific time
# Cron expression format: "0 2 * * *" = 2 AM every day
# "*/15 * * * *" = every 15 minutes
# "0 9-17 * * 1-5" = every hour from 9AM to 5PM on weekdays

# APScheduler gotchas:
# - In a multi-instance deployment, EVERY instance runs the job
#   (not distributed-safe). Use a database job store with
#   misfire_grace_time and coalesce to mitigate.
# - Jobs are lost on process restart (unless using persistent job store)
# - Long-running jobs block the event loop (run in executor)
# - No built-in retry on failure (need custom error handling)
```

### APScheduler with persistent job store

```python
# To survive restarts, use a persistent job store (SQLAlchemy or Redis).

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.executors.pool import ThreadPoolExecutor, ProcessPoolExecutor

jobstores = {
    "default": SQLAlchemyJobStore(url="sqlite:///apscheduler.db")
    # Or for PostgreSQL:
    # "default": SQLAlchemyJobStore(url="postgresql+psycopg2://user:pass@localhost/scheduler")
}

executors = {
    "default": ThreadPoolExecutor(max_workers=10),
    "process": ProcessPoolExecutor(max_workers=5),
}

job_defaults = {
    "coalesce": False,  # Don't coalesce missed executions
    "max_instances": 3,  # Max 3 concurrent instances of the same job
    "misfire_grace_time": 30 * 60,  # 30 minutes grace for late execution
}

scheduler = AsyncIOScheduler(
    jobstores=jobstores,
    executors=executors,
    job_defaults=job_defaults,
    timezone="UTC",
)

# With persistent job store:
# - Jobs survive process restarts (they're stored in the database)
# - coalesce=True: if multiple executions were missed, run only once
# - misfire_grace_time: if the scheduler was down, run the job
#   within this window after restart
# - max_instances: prevent overlapping executions of the same job

# But: distributed safety is still not guaranteed. If two app instances
# share the same database job store, they might both try to execute
# the same job. APScheduler's database job store uses row locking
# to prevent this, but it's not as robust as Celery's approach.
```

### Celery Beat — distributed scheduled tasks

```python
# Celery Beat is the distributed cron for Celery. It sends tasks
# to a message queue (Redis/RabbitMQ). Celery workers consume
# and execute them. Only one worker executes each task.

# tasks.py
from celery import Celery
from celery.schedules import crontab

celery = Celery("tasks", broker=REDIS_URL, backend=REDIS_URL)

# Periodic task definition
@celery.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    # Every hour
    sender.add_periodic_task(3600, cleanup.s(), name="hourly cleanup")
    
    # Every day at 2 AM
    sender.add_periodic_task(
        crontab(hour=2, minute=0),
        daily_report.s(),
        name="daily report",
    )
    
    # Every Monday at 9 AM
    sender.add_periodic_task(
        crontab(hour=9, minute=0, day_of_week="mon"),
        weekly_summary.s(),
        name="weekly summary",
    )

@celery.task
async def cleanup():
    await cleanup_old_sessions()
    await flush_expired_cache()

@celery.task
async def daily_report():
    await generate_daily_report()

# Run Celery Beat (sends tasks to queue):
# $ celery -A tasks beat --loglevel=info

# Run Celery workers (execute tasks):
# $ celery -A tasks worker --loglevel=info --concurrency=4

# Advantages over APScheduler:
# - Distributed-safe: only one worker executes each task
# - Persistent: tasks survive broker restart (with durable queue)
# - Retries: automatic retry on failure (with exponential backoff)
# - Monitoring: Flower dashboard for task monitoring
# - Rate limiting: limit task execution rate
# - Priority: task priority queues

# For FastAPI integration:
# Call tasks from endpoints:
@app.post("/trigger-report/")
async def trigger_report():
    # Send task to queue (doesn't wait for execution)
    daily_report.delay()
    return {"status": "report scheduled"}
    
    # Or with ETA (schedule for later):
    # daily_report.apply_async(eta=datetime.now() + timedelta(hours=1))
```

### Kubernetes CronJob — orchestration-level scheduling

```yaml
# k8s/cronjob.yaml — run a scheduled job in Kubernetes

apiVersion: batch/v1
kind: CronJob
metadata:
  name: daily-report
spec:
  schedule: "0 2 * * *"  # Every day at 2 AM UTC
  concurrencyPolicy: Forbid  # Don't run if previous job is still running
  startingDeadlineSeconds: 200  # If missed, start within 200s
  successfulJobsHistoryLimit: 3  # Keep 3 successful job records
  failedJobsHistoryLimit: 1  # Keep 1 failed job record
  jobTemplate:
    spec:
      template:
        spec:
          containers:
            - name: report
              image: myregistry/fastapi-api:v1.2.3
              command: ["python", "-m", "jobs.daily_report"]
              env:
                - name: ENVIRONMENT
                  value: "production"
                - name: DATABASE_URL
                  valueFrom:
                    secretKeyRef:
                      name: app-secrets
                      key: database-url
              resources:
                requests:
                  memory: "1Gi"
                  cpu: "500m"
                limits:
                  memory: "2Gi"
                  cpu: "1000m"
          restartPolicy: OnFailure  # Restart only if job fails
```

### Idempotency — the critical requirement for scheduled jobs

```python
# Scheduled jobs MUST be idempotent — running them twice should
# produce the same result as running them once. This is critical
# because:
# - The job might be retried after a failure
# - Multiple instances might try to run it (before distributed locking)
# - A restarted job might re-execute

# Non-idempotent (BAD):
async def send_daily_emails():
    # If this runs twice, users get two emails
    for user in users:
        await send_email(user, "daily report")

# Idempotent (GOOD):
async def send_daily_emails():
    # Check if email was already sent today
    today = datetime.utcnow().date()
    for user in users:
        if not await email_sent_today(user.id, today):
            await send_email(user, "daily report")
            await mark_email_sent(user.id, today)

# Idempotency patterns:
# 1. Deduplication key — store a unique key for each execution.
#    Skip if the key already exists.
# 2. Upsert — use INSERT ... ON CONFLICT UPDATE instead of INSERT.
# 3. State-based — check the current state before acting.
#    Only transition if the state allows it.
# 4. Idempotency token — generate a unique token per execution.
#    Store it and check before acting.
# 5. Set-based operations — use SET (Redis) or UPDATE with WHERE
#    clause instead of incrementing counters.

# For ML model evaluation:
async def evaluate_model():
    # Non-idempotent: creates a new evaluation record every run
    # Idempotent: upserts evaluation for today's date
    today = datetime.utcnow().date()
    metrics = await compute_metrics()
    
    # Upsert — if today's evaluation exists, update it
    await db.execute(
        """
        INSERT INTO model_evaluations (date, accuracy, precision, recall)
        VALUES (:date, :accuracy, :precision, :recall)
        ON CONFLICT (date) DO UPDATE
        SET accuracy = EXCLUDED.accuracy,
            precision = EXCLUDED.precision,
            recall = EXCLUDED.recall
        """,
        {"date": today, **metrics},
    )
```

### Job locking — preventing duplicate execution

```python
# For distributed systems where multiple instances might try to
# run the same job, use distributed locking.

# Redis-based lock (using redis-py):
import redis.asyncio as redis
from redis.asyncio.lock import Lock

redis_client = redis.from_url(REDIS_URL)

async def run_with_lock(job_name: str, func, timeout: int = 3600):
    """Acquire a distributed lock before running a job"""
    lock_key = f"lock:{job_name}"
    
    # Try to acquire lock with timeout
    async with redis_client.lock(lock_key, timeout=timeout, blocking_timeout=5) as lock:
        # We have the lock — no other instance can run this job
        await func()
        # Lock is automatically released when exiting the context
        # (or after timeout, preventing deadlocks if the job crashes)

# Usage in scheduled job:
async def daily_report_with_lock():
    await run_with_lock("daily_report", generate_daily_report, timeout=7200)

# If another instance tries to run the same job while the lock
# is held, it blocks (up to blocking_timeout) or fails immediately.
# The lock automatically expires after timeout (preventing deadlock
# if the job crashes without releasing the lock).

# Alternative: database-based locking
# Use SELECT ... FOR UPDATE or a dedicated lock table.
# The database ensures only one instance acquires the lock.

# APScheduler with Redis lock:
@scheduler.scheduled_job(CronTrigger(hour=2, minute=0))
async def daily_report():
    lock_key = "lock:daily_report"
    acquired = await redis_client.set(lock_key, "1", nx=True, ex=7200)
    
    if not acquired:
        # Another instance is running the job
        logger.info("Daily report already running on another instance")
        return
    
    try:
        await generate_daily_report()
    finally:
        await redis_client.delete(lock_key)
```

## Common mistakes / gotchas

- **Running scheduled jobs on every instance** — if you have 4 uvicorn workers and use APScheduler, the job runs 4 times. Use distributed locking or Celery Beat to ensure single execution.
- **Jobs that outlive their schedule** — if a job takes 2 hours and is scheduled hourly, the next execution starts before the first finishes. Use max_instances=1 or concurrencyPolicy=Forbid to prevent overlap.
- **No error handling in scheduled jobs** — if a job fails silently, you never know. Always wrap jobs in try/except, log errors, and send alerts on failure. Use Celery's automatic retries for transient failures.
- **Timezone confusion** — cron schedules are in a specific timezone. If your scheduler uses UTC but your users expect local time, jobs run at the wrong time. Always specify timezone explicitly. Use UTC internally, convert for display.
- **Jobs that depend on running app state** — if a job needs the FastAPI app context (database connections, loaded models), make sure the job starts after the app is ready. Use lifespan events or initialize dependencies in the job itself.
- **Not monitoring scheduled jobs** — if a job silently fails or is skipped, you don't know. Set up monitoring: log every execution, track duration, alert on failures. For Celery, use Flower. For APScheduler, add logging. For Kubernetes CronJob, check job logs.
- **Hardcoded schedule in code** — if the schedule needs to change (e.g., run daily instead of hourly), you need to redeploy. Use configuration (env vars, database) for schedules. Celery Beat supports dynamic schedule changes via the database.
- **Long-running jobs blocking the event loop** — if a scheduled job runs on the event loop and takes a long time, it blocks all requests. Run heavy jobs in a separate process or use Celery workers.

## Practice

> [!question]- Q1. Design a scheduled job system for a FastAPI ML inference API with: (1) daily model evaluation (2 AM), (2) hourly cache warming (every hour), (3) weekly model retraining (Sunday 3 AM), (4) cleanup of stale inference results (every 6 hours). The system runs on 3 Kubernetes replicas. Ensure each job runs exactly once.
**Answer:** Use Kubernetes CronJob for all scheduled jobs. Each CronJob creates a pod that runs the job. Kubernetes ensures only one pod runs per schedule (concurrencyPolicy: Forbid). The jobs are independent of the API replicas — they run in separate pods. (1) Daily model evaluation: CronJob with schedule "0 2 * * *", runs a Python script that loads the latest model, evaluates on validation set, stores metrics in DB. (2) Hourly cache warming: CronJob with schedule "0 * * * *", runs a script that pre-loads popular inference results into Redis cache. (3) Weekly retraining: CronJob with schedule "0 3 * * 0", runs the training pipeline, saves new model to model registry. (4) Cleanup: CronJob with schedule "0 */6 * * *", deletes inference results older than 30 days. Each job uses a database lock (SELECT FOR UPDATE) as a backup safety mechanism in case Kubernetes scheduling fails. Jobs are idempotent (upsert metrics, check-before-delete). Monitoring: each job logs to stdout (captured by Kubernetes), Prometheus metrics for job duration and success rate, alert on failure. Key design: CronJob for distributed safety, separate pods for isolation, idempotent operations for retry safety, monitoring for observability.

> [!question]- Q2. A scheduled job that sends daily emails at 8 AM sometimes sends duplicate emails to the same user. Diagnose and fix.
**Answer:** The job is not idempotent. Possible causes: (1) The job was retried after a partial failure — some emails were sent, then the job crashed and restarted, sending again. (2) Multiple instances of the job ran (distributed system without locking). (3) The email service retried after a timeout, delivering the same email twice. Fix: (1) Make the job idempotent — track which emails were sent for each day (e.g., `email_sent` table with user_id + date composite key). Before sending, check if already sent. (2) Add distributed locking — use Redis lock to ensure only one instance runs. (3) Use idempotency keys when calling the email service — the email service deduplicates based on the key. (4) Use a transaction — mark all emails as "pending", send them, then mark as "sent". If the job crashes, only pending emails are retried. The key insight: any operation that has side effects (sending emails, charging money, creating resources) must be idempotent or have deduplication. The "exactly once" guarantee is impossible in distributed systems — design for "at most once" with idempotency.

> [!question]- Q3. Compare APScheduler, Celery Beat, and Kubernetes CronJob for a FastAPI application. When would you choose each, and what are the migration paths between them?
**Answer:** APScheduler: in-process, Python-native, simplest. Choose for: single-instance deployments, development, lightweight tasks that share app state. Don't choose for: production multi-instance, critical tasks requiring persistence. Celery Beat: distributed, message-queue based, most feature-rich. Choose for: production distributed systems, tasks requiring retries/monitoring/rate limiting, when you already use Celery for background tasks. Don't choose for: simple single-instance apps (overkill). Kubernetes CronJob: orchestration-level, container-based. Choose for: K8s deployments, batch jobs, data processing, when you want isolation (separate pod per job). Don't choose for: non-K8s deployments, tasks needing app context (harder to share). Migration path: APScheduler → Celery Beat: extract job logic into Celery tasks, replace APScheduler decorators with Celery Beat schedule, keep the same job code. APScheduler → Kubernetes CronJob: extract job logic into a separate script/entrypoint, create a CronJob that runs the container with that entrypoint, remove APScheduler from the app. Celery Beat → Kubernetes CronJob: convert Celery tasks to standalone scripts, create CronJobs for each scheduled task, keep Celery for async background tasks (not scheduled). The key: keep job logic independent of the scheduler so you can switch schedulers without rewriting jobs.

> [!question]- Q4. Your scheduled job runs at 2 AM every day. The job sometimes takes 3 hours (when processing large datasets). The next day's job starts while the previous one is still running, causing resource contention and data corruption. Fix this.
**Answer:** The job schedule doesn't account for execution time. Fixes: (1) **Concurrency policy** — set concurrencyPolicy=Forbid (Kubernetes) or max_instances=1 (APScheduler) or task_acks_late + worker_prefetch_multiplier=1 (Celery). This prevents a new job from starting while one is running. The next scheduled execution is skipped if the previous is still running. (2) **Time-based skip** — check at the start of the job if a previous instance is still running. If so, exit early. Use a lock or a "running" flag in the database. (3) **Adjust schedule** — move the job to a time when it's less likely to overlap (e.g., 12 AM instead of 2 AM, giving more time before the next scheduled run). (4) **Optimize the job** — if the job consistently takes 3 hours, optimize it (parallel processing, better algorithms, incremental processing) to reduce runtime. (5) **Break into smaller jobs** — split the daily job into hourly incremental jobs. Each processes a smaller chunk, reducing the chance of overlap. Recommended: combine (1) concurrency policy to prevent overlap + (4) optimization to reduce runtime + (5) incremental processing to make the job faster and more resilient. The concurrency policy is the immediate fix. Optimization and incremental processing are long-term improvements.

> [!question]- Q5. A FastAPI app uses APScheduler for a daily cleanup job. After deploying a new version, the job doesn't run for 24 hours. Diagnose and fix.
**Answer:** Possible causes: (1) **Scheduler not started** — the new version's lifespan event didn't start the scheduler (bug in deployment). Check if scheduler.start() is called. (2) **Timezone shift** — the new version uses a different timezone, so the cron schedule is off by the timezone difference. Check scheduler timezone configuration. (3) **Job store mismatch** — if using persistent job store, the new version's job definitions don't match the stored jobs. The scheduler loads jobs from the store but the function references are broken. Check job store compatibility. (4) **Deployment timing** — the deployment happened right before the scheduled time, and the scheduler missed the window. Check misfire_grace_time. If the scheduler was down during the scheduled time and misfire_grace_time is too short, the job is skipped. (5) **Process restart** — if using non-persistent job store, jobs are lost on restart. The scheduler starts with no jobs. Fix: use persistent job store or re-add jobs on startup. Diagnosis: check scheduler logs (did it start? did it schedule jobs?). Check job store (are jobs persisted?). Check timezone (is it consistent?). Check deployment time vs scheduled time (was there a miss?). Fix based on cause: ensure scheduler.start() is in lifespan, use persistent job store, set appropriate misfire_grace_time (e.g., 30 minutes), verify timezone consistency across deployments.

## Related
[[background-tasks]]
[[background-workers-queues]]
[[logging-and-monitoring]]
[[deployment-docker-uvicorn]]
[[database-integration-async-orm]]

#status/new