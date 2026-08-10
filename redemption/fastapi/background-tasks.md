# Background Tasks

## What it is
FastAPI's `BackgroundTasks` lets you run code after returning the HTTP response to the client. This is useful for operations that don't need to block the request: sending emails, clearing caches, writing audit logs, triggering downstream jobs. The tasks run in the same process after the response is sent. For heavier work (minutes-long jobs, retries, persistence), use a proper queue (Celery, ARQ, Huey) instead.

## Why it matters
Background tasks prevent the client from waiting for non-essential work. But they're fragile — if the process crashes mid-task, the task is lost. Understanding when to use `BackgroundTasks` vs a real queue is a common interview distinction and a critical production decision.

## Core example

```python
from fastapi import BackgroundTasks, FastAPI
from fastapi.mail import EmailMessage

app = FastAPI()

def send_email(email: str, message: str):
    # This runs AFTER the response is sent
    # If it fails, the client already got the response
    ...

@app.post("/send-email/")
async def send_email_endpoint(
    email: str,
    message: str,
    background_tasks: BackgroundTasks,  # FastAPI injects this
):
    # Return immediately
    background_tasks.add_task(send_email, email, message)
    return {"message": "Email will be sent shortly"}
    # The client gets this response instantly.
    # send_email runs in the background.

# Multiple tasks:
@app.post("/process/")
async def process(data: Data, background_tasks: BackgroundTasks):
    background_tasks.add_task(log_audit, data)
    background_tasks.add_task(send_notification, data)
    background_tasks.add_task(update_cache, data)
    # Tasks run in order of addition
    return {"status": "accepted"}

# Tasks with dependencies (cleanup after):
def cleanup(temp_file: str):
    os.remove(temp_file)

@app.post("/upload/")
async def upload(file: UploadFile, background_tasks: BackgroundTasks):
    temp = save_temp(file)
    background_tasks.add_task(cleanup, temp)
    return {"filename": file.filename}
    # File is deleted after response, even if upload processing fails

# Gotcha: if the process crashes (OOM, kill -9, power loss),
# background tasks that haven't run yet are lost. They're not
# persisted. For critical work (payments, order processing),
# use a queue with persistence.
```

## Common mistakes / gotchas

- **Assuming background tasks always run** — if the process exits before the task completes, the task is lost. Not for critical work.
- **Long-running tasks in BackgroundTasks** — a 5-minute task blocks the worker process. Use a queue for anything over a few seconds.
- **Error handling** — exceptions in background tasks aren't caught by FastAPI's exception handlers. Wrap task functions in try/except.
- **Database sessions** — if the task uses a DB session, make sure it creates its own. The request's session may be closed by the time the task runs.

## Practice

> [!question]- Q1. When would you use `BackgroundTasks` vs a Redis-backed queue like Celery? Give specific criteria.
**Answer:** Use `BackgroundTasks` when: the task is non-critical (email, cache clear, audit log), short (< 30s), can be lost if the process crashes, and needs no retry logic. Use a queue when: the task is critical (payment, order, notification), long-running (> 30s), needs retry on failure, needs monitoring/result tracking, or must survive process restarts. The key distinction: `BackgroundTasks` is in-process and volatile; a queue is out-of-process and persistent.

## Related
[[background-workers-queues]]
[[request-response-lifecycle]]

#status/new