# WebSockets

## What it is
WebSocket is a full-duplex communication protocol over a single TCP connection — both client and server can send messages at any time without request/response cycles. FastAPI has built-in WebSocket support via the ASGI spec. This file covers WebSocket lifecycle (connect, receive, disconnect), connection management, broadcasting to multiple clients, authentication for WebSockets, the difference between WebSocket and SSE, and common patterns (chat, real-time notifications, live dashboards, model streaming).

## Why it matters
WebSocket is the right tool when you need real-time, bidirectional communication. But it's also a common source of bugs: connection leaks, memory leaks from untracked connections, auth bypass, and scaling issues across multiple server instances. In interviews, WebSocket questions test whether you understand the protocol, connection lifecycle, and scaling challenges. For your work — streaming ML inference results, real-time model monitoring, live dashboards for training progress — WebSocket is the natural fit.

## Core example

### Basic WebSocket endpoint

```python
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import json

app = FastAPI()

class ConnectionManager:
    """Manages WebSocket connections and broadcasting"""
    
    def __init__(self):
        self.active_connections: list[WebSocket] = []
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
    
    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
    
    async def send_personal(self, message: str, websocket: WebSocket):
        await websocket.send_text(message)
    
    async def broadcast(self, message: str):
        """Send message to all connected clients"""
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception:
                # Connection may have been closed
                # Remove it from the list
                self.active_connections.remove(connection)

manager = ConnectionManager()

@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    await manager.connect(websocket)
    
    try:
        while True:
            # Receive message from client
            data = await websocket.receive_text()
            
            # Echo back to the client
            await manager.send_personal(
                f"You sent: {data}", websocket
            )
            
            # Broadcast to all other clients
            await manager.broadcast(
                f"Client {client_id} says: {data}"
            )
    except WebSocketDisconnect:
        # Client disconnected
        manager.disconnect(websocket)
        await manager.broadcast(f"Client {client_id} left the chat")
```

### WebSocket lifecycle — the states

```python
# WebSocket connection states (ASGI spec):
# 1. CONNECTING — client sent WebSocket handshake, server hasn't accepted
# 2. OPEN — connection established, both sides can send messages
# 3. CLOSING — close handshake in progress
# 4. CLOSED — connection terminated

# In FastAPI, the endpoint receives the WebSocket object in CONNECTING state.
# You must call await websocket.accept() to move to OPEN state.
# If you don't accept, the connection stays in CONNECTING and eventually times out.

# After accept(), you can:
# await websocket.receive_text()  # Receive text message
# await websocket.receive_bytes()  # Receive binary message
# await websocket.receive_json()  # Receive and parse JSON message
# await websocket.send_text(data)  # Send text message
# await websocket.send_bytes(data)  # Send binary message
# await websocket.send_json(data)  # Send JSON message
# await websocket.close(code=1000)  # Close connection

# Close codes (WebSocket standard):
# 1000 — Normal closure
# 1001 — Going away (server shutdown)
# 1002 — Protocol error
# 1003 — Unsupported data type
# 1008 — Policy violation
# 1011 — Internal error
# 1015 — TLS handshake (reserved)

# Proper cleanup:
@app.websocket("/ws/")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    
    try:
        while True:
            data = await websocket.receive_text()
            await websocket.send_text(f"Echo: {data}")
    except WebSocketDisconnect:
        # Client disconnected gracefully
        # Clean up: remove from connection manager, save state, etc.
        pass
    except Exception as e:
        # Connection error or protocol violation
        # Close with appropriate code
        await websocket.close(code=1011)
    finally:
        # Always clean up
        # Remove from connection manager, release resources
        pass
```

### WebSocket authentication — securing the connection

```python
# WebSocket authentication is trickier than HTTP because
# WebSocket doesn't support standard auth headers in the same way.
# But you can authenticate during the handshake.

from fastapi import WebSocket, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
import jwt

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")

async def verify_websocket_token(websocket: WebSocket):
    # Extract token from query params or subprotocol
    # Query params: ws://example.com/ws?token=abc123
    # Subprotocol: WebSocket(..., subprotocols=["bearer-abc123"])
    
    token = websocket.query_params.get("token")
    if not token:
        # Close connection immediately (no auth)
        await websocket.close(code=1008)  # Policy violation
        raise WebSocketDisconnect()
    
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        websocket.state.user_id = payload["sub"]
    except JWTError:
        await websocket.close(code=1008)
        raise WebSocketDisconnect()

@app.websocket("/ws/")
async def websocket_endpoint(websocket: WebSocket):
    # Authenticate before accepting
    await verify_websocket_token(websocket)
    
    # Only accept if auth passed
    await websocket.accept()
    
    # Now you can use websocket.state.user_id
    ...

# Alternative: use a dependency-like pattern
async def get_current_websocket_user(websocket: WebSocket):
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=1008)
        raise WebSocketDisconnect()
    
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        return payload["sub"]
    except JWTError:
        await websocket.close(code=1008)
        raise WebSocketDisconnect()

@app.websocket("/ws/")
async def websocket_endpoint(websocket: WebSocket):
    user_id = await get_current_websocket_user(websocket)
    await websocket.accept()
    # Now you have the authenticated user
    ...

# Security note: using query params for tokens means the token
# appears in server logs and browser history. For production,
# use the subprotocol header or a custom header (if your client
# supports it). The subprotocol approach:
# WebSocket(url, subprotocols=["bearer-<token>"])
# Access via: websocket.headers.get("sec-websocket-protocol")
```

### Scaling WebSockets across multiple instances

```python
# The ConnectionManager with an in-memory list works for a single
# server instance. But if you have 4 uvicorn workers or multiple
# server instances, each has its own connection list. A message
# sent to one instance won't reach clients connected to another.

# Solution: use Redis Pub/Sub to broadcast across instances.

import redis.asyncio as redis
import json

class RedisConnectionManager:
    def __init__(self, redis_url: str):
        self.redis = redis.from_url(redis_url)
        self.pubsub = self.redis.pubsub()
        self.pubsub.subscribe("websocket_broadcast")
    
    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        # Store connection in Redis (or keep local + use Redis for broadcast)
        await self.redis.set(f"ws:{client_id}", websocket_id)
        # Also track locally for this instance
        self.local_connections[client_id] = websocket
    
    async def broadcast(self, message: str):
        # Publish to Redis — all instances receive
        await self.redis.publish("websocket_broadcast", message)
    
    async def listen(self):
        """Listen for messages from Redis and send to local clients"""
        async for message in self.pubsub.listen():
            if message["type"] == "message":
                data = message["data"].decode()
                # Send to all local connections
                for client_id, ws in self.local_connections.items():
                    try:
                        await ws.send_text(data)
                    except:
                        # Connection closed
                        del self.local_connections[client_id]

# Each instance runs a background task that listens to Redis
# and forwards messages to locally connected clients.
# When any instance broadcasts, all instances receive via Redis
# and forward to their local clients.

# Alternative: use a dedicated message broker (Redis, RabbitMQ, Kafka)
# for WebSocket scaling. The pattern is the same — pub/sub across
# instances, local delivery to connected clients.

# For ML inference streaming: the model inference runs on one instance,
# but the result needs to go to the client connected to any instance.
# Use Redis to relay: inference result → Redis Pub/Sub → all instances
# → client connection.
```

### WebSocket for ML inference streaming

```python
# For ML inference, WebSocket is useful when:
# 1. The inference takes a long time and you want to stream progress
# 2. The model produces a stream of results (e.g., token-by-token for LLMs)
# 3. You want to cancel an in-progress inference

@app.websocket("/ws/infer/")
async def inference_stream(websocket: WebSocket):
    # Authenticate
    token = websocket.query_params.get("token")
    if not valid_token(token):
        await websocket.close(code=1008)
        return
    
    await websocket.accept()
    
    try:
        while True:
            # Receive inference request
            data = await websocket.receive_json()
            model = data["model"]
            inputs = data["inputs"]
            
            # Stream inference results
            async for result in model.stream_inference(model, inputs):
                # Send partial results as they're available
                await websocket.send_json({
                    "type": "partial",
                    "result": result,
                    "progress": result.get("progress", 0),
                })
            
            # Send final result
            await websocket.send_json({
                "type": "final",
                "result": final_result,
            })
            
    except WebSocketDisconnect:
        # Client disconnected — cancel any ongoing inference
        cancel_inference(client_id)
    except Exception as e:
        await websocket.send_json({
            "type": "error",
            "message": str(e),
        })
        await websocket.close(code=1011)

# For LLM token streaming:
async def stream_llm_inference(model, prompt):
    """Generator that yields tokens as they're generated"""
    for token in model.generate_stream(prompt):
        yield {
            "token": token.text,
            "cumulative_log_prob": token.cumulative_log_prob,
            "finish_reason": None,
        }
    
    # Final token with finish reason
    yield {
        "token": "",
        "finish_reason": "stop",
    }
```

### WebSocket vs SSE — when to use each

```python
# WebSocket: full-duplex, bidirectional, single persistent connection
# Pros: both client and server can send anytime, low latency,
#       efficient for frequent two-way communication
# Cons: more complex, requires connection management, harder to scale,
#       needs a dedicated load balancer (sticky sessions or WebSocket support)
# Use for: chat, real-time collaboration, live dashboards,
#          interactive gaming, bidirectional ML streaming

# SSE (Server-Sent Events): unidirectional, server-to-client only,
# built on HTTP
# Pros: simpler (just HTTP), auto-reconnect, built into browsers
#       (EventSource API), works through standard HTTP proxies,
#       no special load balancer needed
# Cons: server can only send (client can't send via SSE),
#       text-only (no binary), limited to ~6 connections per browser
# Use for: real-time notifications, live scores, stock prices,
#          model training progress updates, any server-push scenario

# SSE implementation in FastAPI:
from fastapi.responses import StreamingResponse

@app.get("/sse/notifications/")
async def sse_notifications(current_user: User = Depends(get_current_user)):
    async def event_generator():
        # Subscribe to a notification channel
        # Yield SSE events as they arrive
        async for notification in user_notifications(current_user.id):
            # SSE format: data: <data>\n\n
            yield f"data: {json.dumps(notification)}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )

# Recommendation: use SSE for server-push only. Use WebSocket for
# bidirectional communication. If you only need server-to-client,
# SSE is simpler and more robust. If you need client-to-server too,
# use WebSocket.
```

## Common mistakes / gotchas

- **Not handling WebSocketDisconnect** — if a client closes the connection without calling close(), the WebSocketDisconnect exception is raised. If you don't catch it, the connection manager still holds a reference to the closed connection → memory leak and failed broadcasts.
- **Accepting before authenticating** — if you call websocket.accept() before verifying auth, the connection is established before you check credentials. Always authenticate before accept(), or close immediately after if auth fails.
- **In-memory connection list with multiple workers** — each uvicorn worker has its own memory. A broadcast from one worker only reaches clients connected to that worker. Use Redis Pub/Sub for multi-instance broadcasting.
- **Not setting connection limits** — an attacker can open thousands of WebSocket connections, exhausting memory. Implement connection limits per IP/user. Close idle connections with a timeout.
- **Sending to closed connections** — if you try to send to a WebSocket that's been closed, it raises an exception. Always catch and remove closed connections from your connection manager.
- **Buffering in reverse proxies** — nginx and other proxies may buffer WebSocket connections. Add proxy_set_header Connection "upgrade" and proxy_set_header Upgrade $http_upgrade in nginx config. For SSE, disable buffering with X-Accel-Buffering: no.
- **No heartbeat/ping** — WebSocket connections can die silently (network issues, NAT timeout). Implement ping/pong to detect dead connections. FastAPI/uvicorn handles this at the protocol level, but you may want application-level heartbeats.
- **Large messages without fragmentation** — WebSocket has a default message size limit. For large messages (model outputs, file transfers), use binary messages or fragment large messages. Configure uvicorn's --limit-concurrency appropriately.

## Practice

> [!question]- Q1. Design a WebSocket-based chat system for a FastAPI API with: (1) private messages between users, (2) group chat rooms, (3) message history for offline users, (4) typing indicators, (5) read receipts, (6) scale to 10,000 concurrent users across 5 server instances.
**Answer:** Architecture: (1) **Connection management** — Redis-backed connection manager tracking user_id → instance + websocket_id. Each instance tracks its local connections. (2) **Private messages** — look up recipient's connection via Redis. If online, send via WebSocket (through Redis Pub/Sub to the right instance). If offline, store in DB for delivery when they come online. (3) **Group rooms** — Redis sets tracking room_id → set of user_ids. When a message is sent to a room, broadcast to all online members via Redis Pub/Sub. (4) **Message history** — all messages stored in DB. On connection, send recent history (last 50 messages) for the relevant rooms/DMs. (5) **Typing indicators** — lightweight WebSocket messages broadcast to room members with a short TTL (auto-expire after 5s). (6) **Read receipts** — when a client receives a message, send a read receipt via WebSocket. Store in DB for offline senders. Scaling: 10,000 connections across 5 instances = 2,000 connections per instance. Each connection uses ~10-50KB memory. Total: ~100MB for connections. Use Redis Pub/Sub for cross-instance messaging. Use a separate Redis instance for WebSocket traffic. Database for message persistence. Connection limits per user (max 3 connections). Heartbeat every 30s to detect dead connections. Key design: Redis as the coordination layer between instances, DB for persistence, WebSocket for real-time delivery, fallback to polling for offline users.

> [!question]- Q2. A FastAPI WebSocket endpoint works fine locally but fails behind nginx with 400 Bad Gateway on the WebSocket handshake. Diagnose and fix.
**Answer:** The issue is nginx not properly forwarding the WebSocket upgrade headers. WebSocket handshake requires Upgrade: websocket and Connection: Upgrade headers. If nginx doesn't forward these, the handshake fails. Fix: add these to nginx config:
```nginx
location /ws/ {
    proxy_pass http://fastapi_backend;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_read_timeout 86400s;  # Long timeout for persistent connections
}
```
The key directives: `proxy_http_version 1.1` (required for Upgrade), `proxy_set_header Upgrade $http_upgrade` (passes the Upgrade header), `proxy_set_header Connection "upgrade"` (passes the Connection header). Without these, nginx treats the WebSocket handshake as a regular HTTP request and doesn't upgrade the connection. Also check: nginx version (1.3.13+ for WebSocket), proxy_read_timeout (increase for long-lived connections), and that the FastAPI endpoint path matches the nginx location.

> [!question]- Q3. Compare WebSocket, SSE, and long polling for real-time updates in a FastAPI API. When would you choose each, and what are the trade-offs?
**Answer:** WebSocket: persistent TCP connection, full-duplex (both directions), low latency (~ms), efficient for frequent messages. Trade-offs: requires connection management, harder to scale (sticky sessions or message broker), needs WebSocket-aware load balancer, more complex client code. SSE: persistent HTTP connection, server-to-client only, auto-reconnect, simpler (just HTTP). Trade-offs: unidirectional, text-only, browser connection limit (~6), works through standard HTTP proxies. Long polling: client sends request, server holds it open until data is available, responds, client immediately sends new request. Trade-offs: high overhead (HTTP headers per request), higher latency (round-trip per message), simpler to implement, works everywhere. Choice: WebSocket for bidirectional real-time (chat, collaboration, interactive ML). SSE for server-push only (notifications, progress updates, live feeds). Long polling as fallback when WebSocket/SSE aren't supported (old browsers, restrictive proxies). For FastAPI: WebSocket is built-in and performs best. SSE is easy with StreamingResponse. Long polling is a last resort. Recommendation: default to WebSocket for real-time needs. Use SSE if you only need server push and want simplicity. Use long polling only for compatibility.

> [!question]- Q4. Your FastAPI WebSocket endpoint broadcasts messages to 1000 connected clients. The broadcast takes 5 seconds. Clients complain about latency. Diagnose and optimize.
**Answer:** The issue: broadcasting to 1000 clients sequentially in a loop. Each send_text() awaits one at a time. 1000 clients × 5ms each = 5 seconds. Optimization: (1) **Concurrent sending** — use asyncio.gather() to send to all clients concurrently:
```python
async def broadcast(self, message: str):
    await asyncio.gather(
        *[conn.send_text(message) for conn in self.active_connections],
        return_exceptions=True  # Don't fail on one bad connection
    )
```
This reduces broadcast time to ~5ms (the slowest single send) instead of 5 seconds. (2) **Batch by instance** — if using Redis Pub/Sub, each instance only sends to its local connections (e.g., 200 clients per instance). Concurrent send within the instance. (3) **Binary messages** — if sending large data, use send_bytes() instead of send_text() — binary is faster to parse. (4) **Message compression** — for large messages, compress before sending (gzip) and decompress on client. Reduces network time. (5) **Selective broadcast** — don't send to all clients if only a subset needs the message. Use room/subscription model. For 1000 clients: concurrent sending reduces broadcast from 5s to ~5ms. This is the single biggest optimization. The rest are incremental.

> [!question]- Q5. A FastAPI WebSocket connection drops every 30 seconds when behind a cloud load balancer. The connection works fine locally. Diagnose and fix.
**Answer:** The cloud load balancer (AWS ALB, GCP Load Balancer, Azure LB) has an idle timeout — if no data is sent over the connection for N seconds, the LB closes the connection. Default is often 60 seconds, but some are 30 seconds. The WebSocket connection appears to be idle (no messages) and gets killed. Fix: (1) **Heartbeat/ping** — send a ping message every 20 seconds (less than the LB timeout). The client responds with pong. This keeps the connection alive. Implement at the application level or use WebSocket protocol-level ping/pong. (2) **Configure LB timeout** — increase the idle timeout on the load balancer (e.g., AWS ALB: set idle_timeout.timeout_seconds to 4000). (3) **Application-level heartbeat** — send a JSON message {"type": "heartbeat", "timestamp": ...} every 30 seconds. The client ignores it but the connection stays active. The recommended approach: combine application-level heartbeat (every 20-30s) with increased LB timeout (if you control it). The heartbeat ensures the connection stays alive even if the LB timeout is lower than expected. Also handle reconnection on the client side — when the connection drops, automatically reconnect with exponential backoff.

## Related
[[async-await-and-event-loop]]
[[request-response-lifecycle]]
[[background-tasks]]
[[streaming-responses]]
[[caching]]

#status/new