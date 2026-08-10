# Streaming Responses

## What it is
Streaming responses let FastAPI send data to the client incrementally instead of buffering the entire response in memory. This is essential for large file downloads, real-time logs, ML inference token-by-token, and any scenario where the full response isn't available at once or is too large to hold in memory. This file covers StreamingResponse, generator-based streaming, async generators, file streaming with proper headers, SSE (Server-Sent Events) as a streaming pattern, and the gotchas that break streaming behind reverse proxies.

## Why it matters
Without streaming, a 1GB file download requires 1GB of RAM on the server. A 30-second LLM inference means the client waits 30 seconds before seeing any output. Streaming solves both: constant memory usage regardless of response size, and progressive output that gives the client immediate feedback. In interviews, streaming questions test whether you understand the difference between buffered and streaming responses, memory implications, and backpressure. For your work — serving large model outputs, dataset downloads, real-time logs — streaming is not optional.

## Core example

### StreamingResponse — the basics

```python
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
import time

app = FastAPI()

# A generator that yields chunks of data
def video_stream():
    with open("large-video.mp4", "rb") as video:
        while True:
            chunk = video.read(8192)  # 8KB chunks
            if not chunk:
                break
            yield chunk

@app.get("/video/")
async def stream_video():
    return StreamingResponse(
        video_stream(),
        media_type="video/mp4",
    )

# The key: the generator is consumed lazily. Each chunk is read,
# sent to the client, and discarded. Memory usage is constant
# (8KB per request) regardless of file size.

# Async generator — for I/O-bound streaming
async def async_video_stream():
    async with aiofiles.open("large-video.mp4", "rb") as video:
        while True:
            chunk = await video.read(8192)
            if not chunk:
                break
            yield chunk

@app.get("/video-async/")
async def stream_video_async():
    return StreamingResponse(
        async_video_stream(),
        media_type="video/mp4",
    )

# StreamingResponse accepts:
# - A generator (sync) — FastAPI runs it in a thread pool
# - An async generator — FastAPI awaits it directly
# - Any iterable of bytes
```

### Streaming for ML inference — token by token

```python
# For LLM or streaming inference, yield results as they're ready.
# The client receives partial results incrementally.

async def stream_inference(model, inputs):
    """Async generator that yields inference results as they're computed"""
    # For LLM: yield tokens as they're generated
    for token in model.generate_stream(inputs):
        yield f"data: {json.dumps({'token': token.text, 'finish_reason': None})}\n\n"
    
    # Final message
    yield f"data: {json.dumps({'token': '', 'finish_reason': 'stop'})}\n\n"
    yield ": end\n\n"  # SSE end marker

@app.get("/stream-infer/")
async def stream_infer_endpoint(model_name: str, prompt: str):
    model = get_model(model_name)
    
    return StreamingResponse(
        stream_inference(model, prompt),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )
```

### File streaming with range requests (partial content)

```python
# For large files, support HTTP Range requests. This allows clients
# to resume downloads, seek in videos, and download specific parts.

from fastapi import Request, HTTPException
from pathlib import Path
import os

@app.get("/download/{filename}")
async def download_file(filename: str, request: Request):
    file_path = Path("/data/files") / filename
    
    if not file_path.exists():
        raise HTTPException(404, "File not found")
    
    file_size = file_path.stat().st_size
    
    # Handle Range header (partial content)
    range_header = request.headers.get("Range")
    start = 0
    end = file_size - 1
    status_code = 200
    
    if range_header:
        # Range: bytes=0-1023
        match = re.match(r"bytes=(\d+)-(\d*)", range_header)
        if match:
            start = int(match.group(1))
            end_str = match.group(2)
            end = int(end_str) if end_str else file_size - 1
            end = min(end, file_size - 1)
            status_code = 206  # Partial Content
    
    def file_stream():
        with open(file_path, "rb") as f:
            f.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                chunk_size = min(8192, remaining)
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk
    
    headers = {
        "Content-Type": "application/octet-stream",
        "Content-Length": str(end - start + 1),
        "Accept-Ranges": "bytes",
    }
    
    if status_code == 206:
        headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
    
    return StreamingResponse(
        file_stream(),
        status_code=status_code,
        headers=headers,
    )
```

### Streaming with progress tracking

```python
# When streaming a large file, you might want to track progress
# (for logging, monitoring, or sending to the client).

class ProgressTracker:
    def __init__(self, total: int):
        self.total = total
        self.transferred = 0
        self.start_time = time.time()
    
    def update(self, chunk_size: int):
        self.transferred += chunk_size
        return self.progress
    
    @property
    def progress(self) -> float:
        return self.transferred / self.total if self.total > 0 else 1.0
    
    @property
    def speed(self) -> float:
        elapsed = time.time() - self.start_time
        return self.transferred / elapsed if elapsed > 0 else 0
    
    @property
    def eta(self) -> float:
        remaining = self.total - self.transferred
        speed = self.speed
        return remaining / speed if speed > 0 else float("inf")

@app.get("/download-large/")
async def download_large():
    file_path = Path("/data/large-file.bin")
    file_size = file_path.stat().st_size
    
    tracker = ProgressTracker(file_size)
    
    def stream_with_progress():
        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(65536)  # 64KB chunks
                if not chunk:
                    break
                
                progress = tracker.update(len(chunk))
                
                # Log progress (or send to monitoring)
                logger.info(
                    f"Download progress: {progress*100:.1f}% "
                    f"({tracker.speed/1024/1024:.1f} MB/s)"
                )
                
                yield chunk
    
    return StreamingResponse(
        stream_with_progress(),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="large-file.bin"',
            "Content-Length": str(file_size),
        },
    )
```

### Streaming from external sources — proxying with streaming

```python
# Sometimes you need to stream data from an external source (another API,
# S3, CDN) to the client without buffering it on your server.

import httpx

@app.get("/proxy/{path:path}")
async def proxy_stream(path: str):
    """Stream a response from an external service to the client"""
    
    async with httpx.AsyncClient() as client:
        # Stream the response from the external service
        async with client.stream(
            "GET",
            f"https://external-api.com/{path}",
            timeout=30.0,
        ) as response:
            # Forward status code and headers
            headers = {
                k: v for k, v in response.headers.items()
                if k.lower() not in ["content-length", "transfer-encoding"]
            }
            
            # Stream the content chunk by chunk
            async def content_generator():
                async for chunk in response.aiter_bytes(chunk_size=8192):
                    yield chunk
            
            return StreamingResponse(
                content_generator(),
                status_code=response.status_code,
                headers=headers,
                media_type=response.headers.get("content-type"),
            )

# This is efficient: data flows from external service → your server
# → client without being fully buffered on your server.
# Memory usage is constant (chunk size) regardless of total size.
# Useful for: proxying S3 downloads, streaming from another microservice,
# CDN passthrough, video streaming from external sources.
```

### Streaming with backpressure — when the client is slow

```python
# Backpressure: if the client reads data slowly, the server's send
# buffer fills up. Without backpressure handling, the server keeps
# generating data and runs out of memory.

# StreamingResponse handles this naturally: the generator pauses
# when the client's receive buffer is full. The generator resumes
# when the client catches up. This is built into the ASGI protocol.

# But if you have a fast producer (e.g., generating data quickly)
# and a slow consumer (client on mobile network), you need to
# control the production rate.

async def controlled_stream():
    """Stream with rate limiting to match client speed"""
    import asyncio
    
    for i in range(1000):
        data = generate_data(i)
        yield data
        
        # Check if the client is ready for more
        # This is implicit in ASGI — the generator pauses when
        # the client's socket buffer is full.
        
        # But if you want explicit rate limiting:
        await asyncio.sleep(0.01)  # Max 100 chunks/second

# For very fast producers, consider:
# 1. Batching — send multiple items in one chunk
# 2. Rate limiting — sleep between chunks
# 3. Buffer bounds — limit the queue size between producer and consumer
# 4. Client-side flow control — let the client signal when ready

# The ASGI server (uvicorn) handles socket-level backpressure.
# When the client's TCP receive buffer is full, the OS signals
# the server to stop sending. The generator naturally pauses
# because the send() call blocks (or awaits) until buffer space
# is available. This is automatic — you don't need to do anything.
```

### Streaming vs buffering — when to use each

```python
# BUFFERING (return dict, Pydantic model, or Response with content):
# - The entire response is built in memory
# - Then sent to the client in one go
# - FastAPI serializes the entire response before sending

# Use buffering when:
# - Response is small (< 1MB)
# - You need to compute the full response before sending
#   (e.g., total count, pagination metadata)
# - The client needs the full response to do anything
# - You need Content-Length header (known in advance)

# STREAMING (StreamingResponse):
# - Data is sent incrementally as it's generated
# - Memory usage is constant (chunk size)
# - Client starts receiving immediately

# Use streaming when:
# - Response is large (> 10MB, especially > 100MB)
# - Data is generated incrementally (LLM tokens, real-time logs)
# - You don't know the total size in advance
# - You want to minimize memory usage
# - The client can process partial results
# - You're proxying from another source

# Hybrid approach:
# For responses that have metadata + large content:
# 1. Compute metadata (small, buffered)
# 2. Stream the large content
# 3. Or: send metadata as SSE events, stream content separately

@app.get("/export/")
async def export_data():
    # Compute total count (need full scan — buffered)
    total = await db.count()
    
    # But stream the actual data
    def data_stream():
        # Send first line as metadata (JSON)
        yield json.dumps({"total": total, "format": "ndjson"}).encode() + b"\n"
        
        # Stream each row as NDJSON (newline-delimited JSON)
        for row in db.stream_all():
            yield json.dumps(row).encode() + b"\n"
    
    return StreamingResponse(
        data_stream(),
        media_type="application/x-ndjson",
        headers={
            "Content-Disposition": 'attachment; filename="export.ndjson"',
        },
    )
    # The client reads the first line for metadata, then processes
    # each subsequent line as a data row. Memory: constant.
```

## Common mistakes / gotchas

- **Not setting Content-Length for file downloads** — without Content-Length, the client doesn't know how much to expect. For streaming, you can compute the file size beforehand and set the header. For unknown size, use chunked transfer encoding (automatic with StreamingResponse).
- **Buffering in reverse proxies** — nginx buffers responses by default. For streaming, add `proxy_buffering off;` or `X-Accel-Buffering: no` header. Otherwise, nginx buffers the entire response before sending to the client, defeating the purpose of streaming.
- **Sync generators in async endpoints** — a sync generator in a StreamingResponse runs in a thread pool. This is fine for file I/O. But for async I/O (database, external API), use an async generator. Otherwise, you're blocking a thread.
- **Generators that don't clean up** — if a generator opens a file, database connection, or network stream, make sure it's closed. Use context managers inside the generator or try/finally. The generator may be partially consumed if the client disconnects.
- **Memory leak from unclosed generators** — if the client disconnects mid-stream, the generator may not be fully consumed. FastAPI handles this by closing the generator, but explicit cleanup (using `try...finally` in the generator) is safer.
- **No timeout for long streaming responses** — a streaming response that runs forever (e.g., waiting for events) can hold connections indefinitely. Set a timeout or implement heartbeat. Behind load balancers, configure appropriate timeout values.
- **Mixing streaming with middleware that reads the full response** — some middleware (GZIP, custom response modifiers) reads the entire response before sending it. This defeats streaming. Use streaming-compatible middleware or exclude streaming endpoints from such middleware.
- **Not handling client disconnects** — if the client closes the connection mid-stream, continuing to generate data is wasteful. Check for disconnects (request.scope["disconnected"]) or catch BrokenPipeError / asyncio.CancelledError.

## Practice

> [!question]- Q1. Design a streaming endpoint for a FastAPI API that exports 1 million database records as a CSV file. The endpoint must: (1) use constant memory regardless of record count, (2) include a progress header, (3) support cancellation, (4) work behind nginx.
**Answer:**
```python
@app.get("/export/csv/")
async def export_csv(request: Request):
    # Stream CSV directly from database → client
    
    def generate_csv():
        # CSV header
        yield "id,name,email,created_at\n"
        
        # Stream from database using server-side cursor
        # (avoids loading all rows into memory)
        for row in db.stream_query("SELECT id, name, email, created_at FROM users"):
            # Format as CSV (properly escaped)
            line = csv_row([row.id, row.name, row.email, row.created_at])
            yield line
            
            # Check for client disconnect
            if request.scope.get("disconnected"):
                logger.info("Client disconnected during export")
                return  # Stop generating
    
    # Count total for progress (separate query, but needed for Content-Length estimate)
    # Or use approximate count from table metadata
    total = await db.count("users")
    
    return StreamingResponse(
        generate_csv(),
        media_type="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="users.csv"',
            "X-Total-Records": str(total),
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )
```
Key design: database streaming cursor (not loading all rows into memory), CSV generator yields one row at a time (constant memory), disconnect check stops generation when client leaves, nginx buffering disabled. For progress: use a separate endpoint that checks export status, or include progress as comments in the CSV stream. For true progress tracking, use a background task: start export → return job ID → client polls for progress → downloads when ready.

> [!question]- Q2. A FastAPI streaming endpoint works locally but behind nginx, the client receives all data at once after a 30-second delay. Diagnose and fix.
**Answer:** nginx is buffering the response. By default, nginx buffers responses from the upstream server and sends them to the client only after the response is complete (or the buffer is full). For streaming, this defeats the purpose. Fix: (1) Add `proxy_buffering off;` in the nginx location block for streaming endpoints. (2) Or add the header `X-Accel-Buffering: no` in the FastAPI response — nginx respects this header to disable buffering for that response. (3) Also set `proxy_read_timeout` to a high value (e.g., 3600s) for long-running streams. (4) Set `proxy_http_version 1.1` and `proxy_set_header Connection ""` for keep-alive. The recommended approach: add `X-Accel-Buffering: no` header in the StreamingResponse. This is per-response and doesn't require nginx config changes. For all streaming endpoints, add this header universally. Verify with curl: `curl -N http://api/stream/` — the `-N` flag disables curl's own buffering so you see data as it arrives.

> [!question]- Q3. Compare StreamingResponse, FileResponse, and PlainResponse for serving files. When would you use each?
**Answer:** StreamingResponse: streams data from a generator. Use for: dynamic content (generated on-the-fly), large files from non-file sources (database, external API), when you need custom logic during streaming (progress tracking, transformation). FileResponse: optimized for serving files directly from disk. Use for: static files, downloads from known file paths. It handles range requests, ETag, last-modified, and sendfile() system call (zero-copy, kernel-level file transfer). Most efficient for static files. PlainResponse: returns a static response with pre-computed content. Use for: small responses, API responses, HTML pages. Not for files. For serving a 1GB video file: FileResponse is the best choice (zero-copy via sendfile, range requests, caching headers). For streaming a dynamically generated report: StreamingResponse. For returning a JSON API response: PlainResponse (or return a dict, FastAPI wraps it). The key: FileResponse is optimized for static files. StreamingResponse is for dynamic or non-file content. Don't use StreamingResponse to serve static files — you lose the performance benefits of sendfile and range requests.

> [!question]- Q4. You need to stream 10MB of data to a client on a slow mobile network (50 KB/s). The server generates data at 1 MB/s. Explain what happens without backpressure handling and how the system naturally handles it.
**Answer:** Without backpressure: the server generates 10MB of data at 1 MB/s (10 seconds of generation) but the client receives at 50 KB/s (200 seconds to receive). If the server buffers all generated data, it uses 10MB of RAM waiting for the client to catch up. With 1000 concurrent clients, that's 10GB RAM — OOM. With backpressure (ASGI/TCP level): the OS socket buffer fills up (typically 64KB-1MB). When full, the OS signals the server to stop sending. The generator's yield call blocks (or awaits) until buffer space is available. The server naturally slows down to match the client's receive rate. Memory usage stays at ~buffer size (not total data). The generation rate effectively drops from 1 MB/s to 50 KB/s — matching the client. This is automatic: the TCP flow control mechanism handles it. The generator pauses when the socket buffer is full and resumes when space is available. No code changes needed. The key insight: backpressure is built into the TCP/IP stack and ASGI protocol. The generator doesn't need to do anything special — it naturally produces at the rate the client can consume. This is why streaming is memory-efficient for slow clients.

> [!question]- Q5. A FastAPI streaming endpoint uses an async generator that yields data from a Redis Pub/Sub subscription. The client disconnects but the Redis subscription continues. Design proper cleanup.
**Answer:** The issue: the generator is subscribed to Redis but the client disconnected. The generator keeps receiving messages from Redis, consuming memory and resources. Fix: use try/finally in the generator to unsubscribe on exit, and check for client disconnect:
```python
@app.get("/stream/redis/")
async def stream_redis(request: Request, channel: str):
    async def redis_stream():
        pubsub = redis_client.pubsub()
        await pubsub.subscribe(channel)
        
        try:
            async for message in pubsub.listen():
                # Check if client disconnected
                if request.scope.get("disconnected"):
                    logger.info(f"Client disconnected from channel {channel}")
                    break  # Exit generator
                
                if message["type"] == "message":
                    yield message["data"].decode()
        finally:
            # Always unsubscribe, even on disconnect
            await pubsub.unsubscribe(channel)
            await pubsub.close()
            logger.info(f"Redis subscription closed for channel {channel}")
    
    return StreamingResponse(
        redis_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
```
The key: the `finally` block ensures cleanup happens regardless of how the generator exits (normal completion, client disconnect, exception). The disconnect check prevents unnecessary processing after the client leaves. For production: also set a timeout on the Redis listen (so it doesn't block forever if Redis goes down), and track active subscriptions for monitoring.

## Related
[[async-await-and-event-loop]]
[[request-response-lifecycle]]
[[websockets]]
[[background-tasks]]
[[inference-serving-patterns]]

#status/new