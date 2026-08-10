# Rate Limiting

## What it is
Rate limiting restricts how many requests a client can make to your API within a time window. It prevents abuse (DDoS, brute-force, scraping), protects downstream services (databases, ML models), ensures fair usage, and controls costs. This file covers the algorithms (token bucket, sliding window, fixed window), implementation patterns (in-memory, Redis, middleware vs dependency), and the distinction between rate limiting, throttling, and quotas.

## Why it matters
Every public API needs rate limiting. Without it, a single aggressive client can saturate your database, exhaust your ML inference budget, or take down your service. In interviews, rate limiting is a standard system design question — they want to know which algorithm you'd choose, how you'd distribute it across instances, and how you'd handle edge cases. For your work — especially ML serving where each request costs compute — rate limiting is a cost control mechanism, not just a security feature.

## Core example

### The algorithms — what they actually do

```python
# 1. Fixed Window Counter
# Divide time into fixed windows (e.g., 1 minute). Count requests
# per window. If count exceeds limit, reject.

# Simple but has a problem: if a client sends 100 requests at
# 12:00:59 and another 100 at 12:01:01, that's 200 requests
# in 2 seconds — but both windows allowed 100 each.

# Implementation (Redis):
# key = "rate_limit:{client_id}:{window_start}"
# INCR key
# EXPIRE key window_size
# IF value > limit → reject

# 2. Sliding Window Log
# Track timestamp of every request. Count requests in the last
# window. Remove old timestamps.

# Accurate but memory-intensive — stores every request timestamp.
# Not practical for high-traffic APIs.

# Implementation:
# key = "rate_limit:{client_id}"
# ZADD key timestamp timestamp  (sorted set)
# ZREMRANGEBYKEY 0 (now - window)  (remove old)
# ZCARD key  (count)
# IF count > limit → reject

# 3. Sliding Window Counter (recommended)
# Combine fixed window + sliding window. Use two counters:
# current window count + previous window count. Calculate
# weighted average based on where we are in the current window.

# Accurate AND memory-efficient. The standard choice for
# production rate limiting.

# Redis implementation:
# key_current = "rate_limit:{client_id}:{current_window}"
# key_previous = "rate_limit:{client_id}:{previous_window}"
# 
# count_current = INCR key_current
# EXPIRE key_current window_size
# count_previous = GET key_previous or 0
# 
# # Weighted count: current + (previous * overlap_fraction)
# elapsed = now - window_start
# weighted = count_current + count_previous * (1 - elapsed / window_size)
# 
# IF weighted > limit → reject

# 4. Token Bucket
# A bucket holds tokens. Each request consumes a token. Tokens
# are refilled at a fixed rate. If bucket is empty, reject.

# Allows bursts (up to bucket capacity) but limits average rate.
# Good for APIs that want to allow occasional bursts.

# Implementation:
# key = "rate_limit:{client_id}"
# Store: {tokens, last_refill_time}
# 
# On request:
# tokens = min(bucket_capacity, tokens + (now - last_refill) * refill_rate)
# IF tokens >= 1:
#     tokens -= 1
#     allow
# ELSE:
#     reject
# 
# Store updated {tokens, now}

# 5. Leaky Bucket
# Requests go into a queue (bucket). They're processed at a
# fixed rate. If queue is full, reject.

# Smooths out traffic — processes at constant rate regardless
# of input bursts. Good for protecting downstream services
# that can't handle bursts.

# Implementation: queue with fixed consumption rate.
```

### Middleware-based rate limiting — Redis + sliding window

```python
from fastapi import Request, HTTPException
import time
import redis.asyncio as redis

# Redis connection (single instance, shared across requests)
redis_client = redis.from_url(REDIS_URL)

class RateLimitMiddleware:
    def __init__(self, app, limit: int = 100, window: int = 60):
        self.app = app
        self.limit = limit  # Max requests per window
        self.window = window  # Window size in seconds
    
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        
        # Get client identifier — use API key, JWT user ID, or IP
        # Priority: API key > authenticated user > IP address
        headers = dict(scope["headers"])
        
        # Try API key first
        api_key = headers.get(b"x-api-key")
        if api_key:
            client_id = f"api_key:{api_key.decode()}"
        else:
            # Try JWT from Authorization header
            auth = headers.get(b"authorization", b"").decode()
            if auth.startswith("Bearer "):
                token = auth[7:]
                try:
                    payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
                    client_id = f"user:{payload['sub']}"
                except JWTError:
                    client_id = f"ip:{scope['client'][0]}"
            else:
                client_id = f"ip:{scope['client'][0]}"
        
        # Sliding window counter
        now = int(time.time())
        current_window = now // self.window * self.window
        previous_window = current_window - self.window
        
        key_current = f"rate_limit:{client_id}:{current_window}"
        key_previous = f"rate_limit:{client_id}:{previous_window}"
        
        # Atomic operation via Redis Lua script
        script = """
        local current = redis.call("INCR", KEYS[1])
        if current == 1 then
            redis.call("EXPIRE", KEYS[1], ARGS[1])
        end
        
        local previous = redis.call("GET", KEYS[2]) or 0
        
        local elapsed = ARGS[2] - KEYS[3]
        local weighted = current + previous * (1 - elapsed / ARGS[1])
        
        return {current, previous, weighted}
        """
        
        result = await redis_client.eval(
            script,
            3,  # Number of KEYS
            key_current, key_previous, current_window,
            self.window, now  # ARGs
        )
        
        current_count, previous_count, weighted_count = result
        
        if weighted_count > self.limit:
            # Rate limited
            # Calculate retry-after
            retry_after = self.window - (now % self.window)
            
            # Send 429 response directly (ASGI level)
            response_body = b'{"error": "rate_limit", "message": "Too many requests"}'
            await send({
                "type": "http.response.start",
                "status": 429,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"retry-after", str(retry_after).encode()),
                    (b"x-ratelimit-limit", str(self.limit).encode()),
                    (b"x-ratelimit-remaining", str(max(0, int(self.limit - weighted_count))).encode()),
                    (b"x-ratelimit-reset", str(current_window + self.window).encode()),
                ],
            })
            await send({
                "type": "http.response.body",
                "body": response_body,
            })
            return
        
        # Add rate limit headers to the response
        # We need to intercept the response to add headers
        # This requires wrapping the send function
        original_send = send
        
        async def modified_send(message):
            if message["type"] == "http.response.start":
                headers = message.get("headers", [])
                headers.extend([
                    (b"x-ratelimit-limit", str(self.limit).encode()),
                    (b"x-ratelimit-remaining", str(max(0, int(self.limit - weighted_count))).encode()),
                    (b"x-ratelimit-reset", str(current_window + self.window).encode()),
                ])
                message["headers"] = headers
            await original_send(message)
        
        await self.app(scope, receive, modified_send)

# Register middleware:
# app.add_middleware(RateLimitMiddleware, limit=100, window=60)
```

### Dependency-based rate limiting — per-route granularity

```python
from fastapi import Depends, Request, HTTPException
import redis.asyncio as redis

redis_client = redis.from_url(REDIS_URL)

def rate_limit(limit: int = 100, window: int = 60):
    """Dependency factory for per-route rate limiting"""
    
    async def checker(request: Request, current_user: User = Depends(get_current_user)):
        client_id = f"user:{current_user.id}"
        
        # Simple fixed window (simpler than sliding window)
        # Good enough for most per-route limits
        key = f"rate_limit:{client_id}:{request.url.path}"
        current = await redis_client.incr(key)
        
        if current == 1:
            # First request in this window — set expiry
            await redis_client.expire(key, window)
        
        if current > limit:
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded. {limit} requests per {window}s.",
                headers={"Retry-After": str(window)},
            )
        
        return current
    
    return Depends(checker)

# Usage in endpoints:
@app.post("/comments/", dependencies=[Depends(rate_limit(limit=10, window=60))])
async def create_comment(...):
    # Max 10 comments per minute per user
    ...

@app.post("/login/", dependencies=[Depends(rate_limit(limit=5, window=60))])
async def login(...):
    # Max 5 login attempts per minute per IP
    # (auth happens after rate limit check)
    ...

# The dependency approach is simpler than middleware and gives
# per-route granularity. But it runs AFTER routing and auth,
# so it doesn't protect against unauthenticated abuse.
# Use middleware for global limits, dependency for per-route limits.
```

### Rate limiting for ML inference — cost control

```python
# For ML inference APIs, rate limiting isn't just about preventing abuse
# — it's about controlling compute costs. Each inference costs money
# (GPU time, API calls to other models).

class InferenceRateLimiter:
    def __init__(self, redis_client):
        self.redis = redis_client
    
    async def check(self, user_id: str, model: str, tokens: int = 1):
        """Check if user can make an inference request"""
        
        # Tier-based limits
        tiers = {
            "free": {"rpm": 10, "tpm": 1000, "daily": 100},
            "pro": {"rpm": 100, "tpm": 10000, "daily": 1000},
            "enterprise": {"rpm": 1000, "tpm": 100000, "daily": 10000},
        }
        
        user_tier = await get_user_tier(user_id)
        limits = tiers[user_tier]
        
        now = int(time.time())
        day = now // 86400 * 86400
        minute = now // 60 * 60
        
        # Check requests per minute (RPM)
        rpm_key = f"inference:{user_id}:{model}:rpm:{minute}"
        rpm_count = await self.redis.incr(rpm_key)
        if rpm_count == 1:
            await self.redis.expire(rpm_key, 60)
        if rpm_count > limits["rpm"]:
            return False, "rate_limit", "Requests per minute limit exceeded"
        
        # Check tokens per minute (TPM) — more accurate for LLMs
        tpm_key = f"inference:{user_id}:{model}:tpm:{minute}"
        tpm_count = await self.redis.incrby(tpm_key, tokens)
        if tpm_count == tokens:  # Was 0 before increment
            await self.redis.expire(tpm_key, 60)
        if tpm_count > limits["tpm"]:
            return False, "token_limit", "Tokens per minute limit exceeded"
        
        # Check daily limit
        daily_key = f"inference:{user_id}:{model}:daily:{day}"
        daily_count = await self.redis.incr(daily_key)
        if daily_count == 1:
            await self.redis.expire(daily_key, 86400)
        if daily_count > limits["daily"]:
            return False, "daily_limit", "Daily limit exceeded"
        
        return True, None, None

# Usage in endpoint:
@app.post("/v1/chat/completions")
async def chat_completion(request: Request, current_user: User = Depends(get_current_user)):
    body = await request.json()
    tokens = estimate_tokens(body["messages"])
    
    allowed, reason, message = await rate_limiter.check(
        current_user.id, body["model"], tokens
    )
    
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail={"error": reason, "message": message},
        )
    
    # Proceed with inference
    result = await model.generate(body)
    return result
```

### Rate limit headers — what to include

```python
# Standard rate limit headers (used by clients and load balancers):

# X-RateLimit-Limit — the maximum number of requests allowed
# X-RateLimit-Remaining — the number of requests left in the current window
# X-RateLimit-Reset — the time at which the current window resets (Unix timestamp)
# Retry-After — the number of seconds to wait before retrying (on 429)

# Example response headers:
# X-RateLimit-Limit: 100
# X-RateLimit-Remaining: 95
# X-RateLimit-Reset: 1704067200
# Retry-After: 45  (only on 429 responses)

# These headers allow clients to self-regulate — they can see
# how many requests they have left and when they'll be refreshed.
# Good API clients respect these headers and adjust their request rate.
```

### Bypassing rate limits — when and how

```python
# Some endpoints or clients should be exempt from rate limiting:
# - Internal health checks
# - Admin endpoints (already protected by auth)
# - Whitelisted API keys (partners, enterprise clients)
# - Webhook callbacks from trusted services

# Implementation — check before applying rate limit:
async def is_exempt(client_id: str, path: str) -> bool:
    # Health checks
    if path in ["/health", "/ready", "/live"]:
        return True
    
    # Whitelisted API keys
    if client_id.startswith("api_key:") and client_id in WHITELISTED_KEYS:
        return True
    
    # Admin endpoints (but they should be auth-protected too)
    if path.startswith("/admin/"):
        return True
    
    return False

# In middleware:
if await is_exempt(client_id, scope["path"]):
    await self.app(scope, receive, send)
    return

# The key: exemptions are explicit and auditable. Never exempt
# based on IP address alone (spoofable). Use API keys or JWT claims.
# Log all exemptions for auditing.
```

## Common mistakes / gotchas

- **Using in-memory rate limiting with multiple instances** — if you have 4 uvicorn workers or multiple servers, each has its own memory. A client can make 100 requests to each instance, bypassing the limit. Always use Redis (or another shared store) for distributed rate limiting.
- **Fixed window edge case** — the fixed window algorithm allows 2x the limit at window boundaries. Use sliding window counter for accuracy. This is a common interview trap.
- **Rate limiting before auth** — if you rate limit by IP before authentication, legitimate users behind NAT (corporate networks, universities) share the same IP and get rate-limited together. Rate limit by authenticated user ID when possible, with IP-based fallback for unauthenticated endpoints.
- **Not including rate limit headers** — clients have no way to know their limits without headers. Always include X-RateLimit-* headers and Retry-After on 429.
- **Rate limiting the wrong thing** — rate limiting by request count doesn't account for request cost. A /health check and a /predict endpoint cost very differently. Use tiered limits or token-based limiting for APIs with variable-cost endpoints.
- **Redis as a single point of failure** — if Redis is down, your rate limiting fails. Decide: fail open (allow all requests) or fail closed (reject all requests). Fail open is safer for availability; fail closed is safer for protection. Use Redis with persistence and replication for production.
- **Not cleaning up Redis keys** — rate limit keys with EXPIRE are auto-cleaned. But if you use a different approach (like sorted sets for sliding window log), you need to clean up old entries. Otherwise Redis grows unbounded.
- **Rate limiting in middleware without checking response** — if you add rate limit headers in middleware by wrapping the send function, make sure you only modify http.response.start messages, not other ASGI events. And don't modify the response if it's already a 429 (from another check).

## Practice

> [!question]- Q1. Design a rate limiting strategy for a FastAPI API with the following requirements: (1) Free tier: 100 requests/hour, Pro tier: 1000 requests/hour, Enterprise: 10000 requests/hour, (2) Separate limits for /predict endpoints (more expensive), (3) Burst allowance of 2x the normal rate for 10 seconds, (4) Distributed across 4 server instances.
**Answer:** Use Redis-based sliding window counter with tier-based keys. The design:
```python
# Key structure for tier-based limits:
# rate_limit:{user_id}:{tier}:{endpoint_group}:{window}

# Tier configuration:
TIERS = {
    "free": {"rpm": 2, "burst_rpm": 4, "burst_window": 10},
    "pro": {"rpm": 17, "burst_rpm": 34, "burst_window": 10},
    "enterprise": {"rpm": 167, "burst_rpm": 334, "burst_window": 10},
}

# For /predict endpoints, use a separate, lower limit:
PREDICT_TIERS = {
    "free": {"rpm": 1, "burst_rpm": 2},
    "pro": {"rpm": 5, "burst_rpm": 10},
    "enterprise": {"rpm": 50, "burst_rpm": 100},
}

# Algorithm: sliding window counter with burst detection.
# Normal limit: X requests per minute. Burst: 2X for 10 seconds.
# Implementation: track both 1-minute window and 10-second window.
# If 10-second count > burst_limit → reject.
# If 1-minute count > normal_limit → reject.
# Otherwise allow.

# Redis keys:
# rate_limit:{user_id}:{endpoint_group}:minute:{minute_window}
# rate_limit:{user_id}:{endpoint_group}:burst:{burst_window}

# Both keys are checked atomically via Lua script.
# If either exceeds its limit → 429.
# This is distributed — all 4 server instances share the same Redis,
# so the limit is global across all instances.
```
The key design: separate endpoint groups (/predict vs regular) have different limits. Burst detection uses a shorter window (10s) with 2x limit. Sliding window counter prevents the fixed window edge case. Redis ensures distributed consistency. Tier configuration is centralized and easy to update.

> [!question]- Q2. A client complains they're getting 429 errors even though they're well within their rate limit. They're making 50 requests/minute and their limit is 100/minute. Diagnose the issue.
**Answer:** Possible causes: (1) **Fixed window edge case** — if they hit the boundary between two windows, they could make 50 requests in the last second of window 1 and 50 in the first second of window 2, triggering the limit in both windows. Fix: use sliding window counter. (2) **Multiple instances** — if there are 4 server instances with in-memory rate limiting, each instance tracks separately. The client might be load-balanced across instances. But if they're hitting 429, this isn't the issue (they'd get through more). (3) **Shared IP** — if rate limiting is by IP and the client is behind a NAT (corporate network), other users on the same IP are consuming the quota. Fix: rate limit by authenticated user ID, not IP. (4) **Retry storms** — the client gets one 429 and immediately retries, consuming more quota. Fix: clients should respect Retry-After header. (5) **Different endpoint groups** — the /predict endpoint might have a lower limit than the general API. The client thinks they're at 50/100 but actually hitting 50/10 on /predict. Check which endpoint they're calling. Diagnosis: check the rate limit headers (X-RateLimit-Remaining, X-RateLimit-Reset) to see which limit is being hit. Check the Redis keys for that client to see the actual counts. Check the error response for which specific limit was exceeded.

> [!question]- Q3. Compare rate limiting at the API gateway level vs the FastAPI application level. When would you use each?
**Answer:** API gateway level (nginx, Kong, AWS API Gateway): rate limiting happens before the request reaches your application. Pros: protects the application from ALL traffic (including malformed requests, DDoS), lower latency (no application overhead), centralized across multiple services, can handle higher throughput. Cons: less flexible (can't do user-level limits without auth at gateway), can't do complex logic (tier-based, endpoint-specific), gateway becomes another operational component. FastAPI application level: rate limiting happens in your code. Pros: full flexibility (user-level, tier-based, endpoint-specific, dynamic limits), can use application context (user tier, request cost), integrated with auth. Cons: application processes the request before rejecting (wastes resources), can't protect against application-level DDoS. Recommended approach: both. API gateway for global rate limiting (requests per IP, basic DDoS protection). FastAPI for application-level rate limiting (user tiers, endpoint-specific, cost-based). The gateway handles the bulk of abuse; the application handles fine-grained control. This is the defense-in-depth approach.

> [!question]- Q4. You need to implement rate limiting for a WebSocket endpoint. The standard request-count approach doesn't work because WebSocket is a persistent connection. Design the approach.
**Answer:** For WebSocket, rate limiting applies to message flow, not connection establishment. Two approaches: (1) **Message rate limiting** — count messages per connection per time window. If a client sends more than N messages in T seconds, close the connection or drop messages. Track per-connection counters in Redis (connection_id → message count). Reset counters periodically. (2) **Token bucket per connection** — each WebSocket connection gets a token bucket. Each message consumes a token. Tokens refill at a fixed rate. If no token, drop the message or close the connection. This allows bursts but limits average rate. Implementation: when WebSocket connects, create a token bucket in Redis. On each message, check and consume tokens. If insufficient tokens, send an error message or close. On disconnect, clean up the Redis key. For connection-level rate limiting (how many connections per user), use the same approach as HTTP rate limiting — count connections per user/IP in Redis with TTL. The key difference from HTTP: WebSocket rate limiting is continuous (messages over time) not discrete (requests). The token bucket algorithm is the natural fit.

> [!question]- Q5. Your FastAPI API uses Redis for rate limiting. Redis suddenly becomes unavailable. What happens to your API, and how do you design for this scenario?
**Answer:** If Redis is unavailable, the rate limiting code fails. The question is: does your API fail open (allow all requests) or fail closed (reject all requests)? Fail open: if Redis check fails, allow the request. Pros: API remains available. Cons: no rate limiting — a malicious client can overwhelm the service. Fail closed: if Redis check fails, reject the request with 503 or 429. Pros: protected. Cons: API becomes unavailable. The choice depends on your threat model and availability requirements. For a public API: fail open with alerting — allow requests but alert the team immediately. The risk of no rate limiting is lower than the risk of total outage. For a payment API or ML inference API with cost controls: fail closed — better to reject legitimate requests than to let abuse drain your budget. Design for resilience: (1) Use Redis with replication and persistence — unlikely to fully fail. (2) Add circuit breaker — if Redis fails 5 consecutive times, skip rate limiting for 30 seconds (fail open temporarily). (3) Monitor Redis health — alert on connection failures. (4) Have a fallback — if Redis is down, use in-memory rate limiting (less accurate but better than nothing). (5) Graceful degradation — if Redis is slow, use a shorter timeout on Redis commands and fail open on timeout. The recommended approach: fail open with circuit breaker and aggressive alerting. Rate limiting is important, but availability is more important.

## Related
[[middleware]]
[[caching]]
[[auth-oauth2-jwt]]
[[inference-serving-patterns]]
[[system-design-for-apis-at-scale]]

#status/new