# Caching

## What it is
Caching stores the result of expensive operations so that subsequent identical requests can be served from the cache instead of recomputing. In FastAPI, caching applies to database queries, API responses, ML inference results, and rendered templates. This file covers cache strategies (TTL, write-through, write-behind, cache-aside), cache invalidation patterns, Redis caching, HTTP caching headers, and the distinction between caching and rate limiting (they share infrastructure but solve different problems).

## Why it matters
Caching is the single most effective performance optimization for read-heavy APIs. A well-placed cache can reduce database load by 90%, cut latency from 500ms to 5ms, and drastically reduce infrastructure costs. But caching introduces complexity: stale data, cache invalidation storms, cache stampedes, and consistency issues. In interviews, caching questions test whether you understand cache invalidation strategies, consistency trade-offs, and when caching helps vs hurts. For your work — ML inference APIs where the same prompt might be queried repeatedly, or data APIs with frequent reads — caching is a force multiplier.

## Core example

### Cache strategies — when to use each

```python
# 1. Cache-Aside (Lazy Loading)
# Application checks cache first. If miss, fetches from DB,
# stores in cache, returns result. Simplest and most common.

async def get_user(user_id: int):
    # Check cache first
    cached = await redis.get(f"user:{user_id}")
    if cached:
        return json.loads(cached)
    
    # Cache miss — fetch from DB
    user = await db.get_user(user_id)
    
    # Store in cache with TTL
    await redis.setex(f"user:{user_id}", 3600, json.dumps(user))
    
    return user

# Pros: simple, only caches hot data, cache misses don't affect correctness
# Cons: stale data possible (TTL-based consistency), cache stampede risk
# Best for: read-heavy workloads where occasional stale data is acceptable

# 2. Write-Through
# Every write goes to cache AND database simultaneously.
# Cache always has the latest data.

async def update_user(user_id: int, data: dict):
    # Write to DB
    await db.update_user(user_id, data)
    
    # Update cache immediately
    user = await db.get_user(user_id)  # Or merge data into existing
    await redis.setex(f"user:{user_id}", 3600, json.dumps(user))
    
    return user

# Pros: cache is always consistent with DB
# Cons: write latency increased (must write to both), writes that
#       are never read waste cache space
# Best for: write-once-read-many patterns where consistency is critical

# 3. Write-Back (Write-Behind)
# Write to cache immediately, acknowledge to client, then
# asynchronously write to DB.

async def update_user(user_id: int, data: dict):
    # Update cache immediately
    user = await get_cached_user(user_id)
    user.update(data)
    await redis.set(f"user:{user_id}", json.dumps(user))
    
    # Acknowledge immediately (fast response)
    
    # Asynchronously write to DB (via background task or queue)
    background_tasks.add_task(db.update_user, user_id, data)
    
    return user

# Pros: very fast writes (cache is fast)
# Cons: data loss risk if cache fails before DB write, complex
# Best for: high-write workloads where eventual consistency is acceptable

# 4. Refresh-Ahead
# Proactively refresh cache entries before they expire,
# based on access patterns.

async def get_user(user_id: int):
    cached = await redis.get(f"user:{user_id}")
    if cached:
        # If TTL is less than 10% remaining, refresh in background
        ttl = await redis.ttl(f"user:{user_id}")
        if ttl < 360:  # 10% of 1 hour
            background_tasks.add_task(refresh_user_cache, user_id)
        return json.loads(cached)
    
    # Cache miss — fetch and cache
    ...

# Pros: reduces cache misses for hot data
# Cons: complexity, may refresh data that's no longer needed
# Best for: predictable access patterns with hot data

# Recommendation: cache-aside is the default choice for most APIs.
# Add write-through for critical consistency. Avoid write-back
# unless you have specific high-write requirements and can tolerate
# eventual consistency with durability guarantees.
```

### Cache-aside implementation with FastAPI

```python
from fastapi import Depends
import redis.asyncio as redis
import json

redis_client = redis.from_url(REDIS_URL)

# Cache key builder — consistent naming
def cache_key(entity: str, entity_id: int | str, version: str = "v1") -> str:
    return f"cache:{version}:{entity}:{entity_id}"

# Cache decorator pattern
def cached(ttl: int = 3600, key_prefix: str = "cache"):
    """Decorator for caching function results"""
    
    def decorator(func):
        async def wrapper(*args, **kwargs):
            # Build cache key from function name and arguments
            # For simple cases: use first argument as ID
            key = f"{key_prefix}:{func.__name__}:{args[0]}"
            
            # Check cache
            cached = await redis_client.get(key)
            if cached:
                return json.loads(cached)
            
            # Cache miss — compute
            result = await func(*args, **kwargs)
            
            # Store in cache
            await redis_client.setex(key, ttl, json.dumps(result))
            
            return result
        
        return wrapper
    return decorator

# Usage:
@cached(ttl=3600, key_prefix="user")
async def get_user_from_db(user_id: int):
    # This is only called on cache miss
    return await db.get_user(user_id)

# In endpoint:
@app.get("/users/{user_id}")
async def get_user(user_id: int):
    # Uses cache if available, falls back to DB
    return await get_user_from_db(user_id)

# For more complex cache keys (multiple parameters):
def cache_key_for_search(query: str, page: int, limit: int) -> str:
    return f"cache:search:{hash(query)}:{page}:{limit}"

# Cache invalidation — when data changes:
async def invalidate_user_cache(user_id: int):
    await redis_client.delete(f"cache:user:{user_id}")
    # Also invalidate list caches that might include this user
    await redis_client.delete("cache:users:list")
    # Use cache key patterns for bulk invalidation:
    # await redis_client.delete("cache:user:*")  # But this is slow
    
    # Better: use Redis SCAN with pattern matching
    # Or use a cache version per entity type
```

### Cache invalidation — the hard problem

```python
# Cache invalidation is famously hard. Here are the practical patterns:

# Pattern 1: TTL-based (simplest)
# Set a reasonable TTL (e.g., 5 minutes for product data, 1 hour for user data).
# Data may be stale for up to TTL, but eventually consistent.
# Acceptable for most read-heavy applications.

# Pattern 2: Versioned cache keys
# Include a version number in the cache key. Increment the version
# when data changes — all old keys become inaccessible (effectively
# invalidated).

# User version in DB:
# users table: id, name, email, cache_version (default: 1)

# When user updates:
await db.execute(
    "UPDATE users SET name = $1, cache_version = cache_version + 1 WHERE id = $2",
    new_name, user_id
)

# Cache key includes version:
key = f"user:{user_id}:{user.cache_version}"

# On update, the version changes. The old cache key (with old version)
# is still in Redis but will never be read again. The next read uses
# the new version key → cache miss → fresh data from DB.
# This is cache invalidation without explicit deletion.

# Pattern 3: Cache tags
# Tag cache entries with categories. Invalidate all entries with a tag.

# Redis doesn't natively support tags, but you can implement:
# Store tag → keys mapping in a Redis set

async def set_with_tags(key: str, value, ttl: int, tags: list[str]):
    await redis_client.setex(key, ttl, value)
    for tag in tags:
        await redis_client.sadd(f"tag:{tag}", key)

async def invalidate_tag(tag: str):
    # Get all keys with this tag
    keys = await redis_client.smembers(f"tag:{tag}")
    if keys:
        await redis_client.delete(*keys)
    await redis_client.delete(f"tag:{tag}")

# Usage:
# set_with_tags("user:123", data, 3600, ["user:123", "users:list"])
# invalidate_tag("users:list")  # Invalidates all user list caches

# Pattern 4: Write-through for critical data
# For data that MUST be consistent (e.g., user authentication),
# update the cache at the same time as the DB. No staleness.
# But this couples write latency to cache write latency.

# Recommendation: TTL-based for most data. Versioned cache keys
# for entity-level invalidation. Cache tags for category-level
# invalidation. Write-through only for critical consistency.
```

### Cache stampede prevention — the dogpile problem

```python
# Cache stampede (dogpile effect): a popular cache entry expires.
# Suddenly, 1000 concurrent requests all miss the cache and hit
# the DB simultaneously. The DB crashes.

# Solution 1: Locking (mutex on cache key)
async def get_user(user_id: int):
    key = f"user:{user_id}"
    
    # Try to get from cache
    cached = await redis_client.get(key)
    if cached:
        return json.loads(cached)
    
    # Cache miss — try to acquire lock
    lock_key = f"lock:{key}"
    acquired = await redis_client.set(lock_key, "1", nx=True, ex=10)
    
    if acquired:
        # We got the lock — fetch from DB and populate cache
        try:
            user = await db.get_user(user_id)
            await redis_client.setex(key, 3600, json.dumps(user))
            return user
        finally:
            await redis_client.delete(lock_key)
    else:
        # Someone else is fetching — wait and retry
        await asyncio.sleep(0.1)  # Brief sleep
        # Retry (with limited retries to avoid infinite loop)
        for _ in range(10):
            cached = await redis_client.get(key)
            if cached:
                return json.loads(cached)
            await asyncio.sleep(0.1)
        
        # If still not cached, fetch anyway (fallback)
        user = await db.get_user(user_id)
        return user

# Solution 2: Early expiration with background refresh
# Set cache TTL shorter than the "freshness" requirement.
# When a request finds a nearly-expired cache entry, it serves
# the stale value and triggers a background refresh.

async def get_user(user_id: int):
    key = f"user:{user_id}"
    cached = await redis_client.get(key)
    
    if cached:
        # Check TTL
        ttl = await redis_client.ttl(key)
        
        # If less than 10% of TTL remaining, refresh in background
        if ttl < 360:  # 10% of 1 hour
            background_tasks.add_task(refresh_user_cache, user_id)
        
        return json.loads(cached)
    
    # Cache miss — fetch and cache
    user = await db.get_user(user_id)
    await redis_client.setex(key, 3600, json.dumps(user))
    return user

# Solution 3: Probabilistic early expiration
# Each request that hits a nearly-expired cache has a small
# probability of triggering a refresh. This spreads the refresh
# load across multiple requests instead of one request doing it.

import random

async def get_user(user_id: int):
    key = f"user:{user_id}"
    cached = await redis_client.get(key)
    
    if cached:
        ttl = await redis_client.ttl(key)
        
        # 10% chance to refresh if less than 20% TTL remaining
        if ttl < 720 and random.random() < 0.1:
            background_tasks.add_task(refresh_user_cache, user_id)
        
        return json.loads(cached)
    
    # ... cache miss handling ...
```

### HTTP caching — browser and CDN caching

```python
from fastapi import Response
from datetime import datetime, timedelta

# HTTP caching headers tell browsers and CDNs how long to cache
# the response. This reduces server load and improves latency
# for end users.

@app.get("/public-data/")
async def public_data(response: Response):
    # Cache for 1 hour in browser and CDN
    response.headers["Cache-Control"] = "public, max-age=3600"
    response.headers["Expires"] = (datetime.utcnow() + timedelta(hours=1)).strftime("%a, %d %b %Y %H:%M:%S GMT")
    
    return {"data": "this can be cached"}

# Cache-Control directives:
# public — can be cached by browsers AND CDNs/proxies
# private — only the user's browser can cache (not CDNs)
# no-cache — must revalidate with server before using cached copy
# no-store — don't cache at all (sensitive data)
# max-age=N — cache for N seconds
# s-maxage=N — CDN cache for N seconds (overrides max-age for CDNs)
# stale-while-revalidate=N — serve stale while revalidating in background
# stale-if-error=N — serve stale if origin returns error

# For API responses that change infrequently:
@app.get("/catalog/", response_model=list[Product])
async def get_catalog(response: Response):
    # Cache in CDN for 1 hour, revalidate after
    response.headers["Cache-Control"] = "public, max-age=3600, stale-while-revalidate=60, stale-if-error=86400"
    return await get_all_products()

# For user-specific data — don't cache in CDNs:
@app.get("/me/", response_model=User)
async def get_me(response: Response, current_user: User = Depends(get_current_user)):
    # Only browser cache, no CDN
    response.headers["Cache-Control"] = "private, max-age=300"
    return current_user

# For sensitive data — no caching:
@app.get("/payment-history/", response_model=list[Payment])
async def get_payment_history(response: Response, ...):
    response.headers["Cache-Control"] = "no-store, max-age=0"
    return await get_payments(...)

# ETag — conditional requests
# The server sends an ETag (hash of the response). The client
# sends If-None-Match with the ETag on subsequent requests.
# If the ETag matches, the server returns 304 Not Modified
# (no body — saves bandwidth).

from hashlib import md5

@app.get("/article/{slug}")
async def get_article(slug: str, response: Response, if_none_match: str | None = Header(None)):
    article = await get_article_by_slug(slug)
    
    # Generate ETag from content hash (or version)
    etag = md5(article.content.encode()).hexdigest()
    response.headers["ETag"] = f'"{etag}"'
    
    # If client has the same ETag, return 304
    if if_none_match == f'"{etag}"':
        response.status_code = 304
        return None  # No body
    
    return article
```

### Caching ML inference results

```python
# For ML inference, caching is especially valuable because:
# 1. Inference is expensive (GPU/CPU time)
# 2. The same prompt/image is often queried multiple times
# 3. Results are deterministic (same input → same output)

import hashlib
import json

class InferenceCache:
    def __init__(self, redis_client, ttl: int = 3600):
        self.redis = redis_client
        self.ttl = ttl
    
    def _cache_key(self, model: str, inputs: dict) -> str:
        # Create a deterministic key from model and inputs
        # Hash the inputs to keep the key length manageable
        input_hash = hashlib.sha256(
            json.dumps(inputs, sort_keys=True).encode()
        ).hexdigest()[:16]
        return f"inference:{model}:{input_hash}"
    
    async def get(self, model: str, inputs: dict):
        """Get cached inference result, or None if cache miss"""
        key = self._cache_key(model, inputs)
        cached = await self.redis.get(key)
        if cached:
            return json.loads(cached)
        return None
    
    async def set(self, model: str, inputs: dict, result):
        """Store inference result in cache"""
        key = self._cache_key(model, inputs)
        await self.redis.setex(key, self.ttl, json.dumps(result))
    
    async def invalidate_model(self, model: str):
        """Invalidate all cache entries for a model"""
        # Use Redis SCAN to find all keys for this model
        # Or use cache tags
        keys = await self.redis.keys(f"inference:{model}:*")
        if keys:
            await self.redis.delete(*keys)

# Usage in endpoint:
inference_cache = InferenceCache(redis_client, ttl=86400)  # 24h cache

@app.post("/v1/chat/completions")
async def chat_completion(request: Request):
    body = await request.json()
    model = body["model"]
    inputs = {"messages": body["messages"], "temperature": body.get("temperature", 0.7)}
    
    # Check cache first
    cached = await inference_cache.get(model, inputs)
    if cached:
        # Add header to indicate cache hit
        request.state.cache_hit = True
        return cached
    
    # Cache miss — run inference
    result = await model_inference(model, body)
    
    # Cache the result (but only for successful responses)
    if result.get("error") is None:
        await inference_cache.set(model, inputs, result)
    
    return result

# Considerations for ML caching:
# 1. TTL — how long are inference results valid? For a static model,
#    indefinitely. For a model that's updated frequently, shorter TTL.
# 2. Cache key — must include model version AND all input parameters
#    that affect the output (temperature, max_tokens, etc.).
# 3. Cache size — inference results can be large. Set memory limits
#    and eviction policies (LRU) in Redis.
# 4. Cache invalidation — when the model is updated, invalidate all
#    cache entries for that model. Or use versioned cache keys.
# 5. Partial caching — for streaming responses, cache the full
#    response but stream it to the client.
```

### Redis configuration for caching

```python
# Redis configuration for caching workloads:

# redis.conf (or cloud Redis settings):

# Memory management
maxmemory 4gb  # Limit Redis memory usage
maxmemory-policy allkeys-lru  # Evict least recently used keys

# When maxmemory is reached, Redis evicts keys based on policy:
# noeviction — return errors (writes fail)
# allkeys-lru — evict least recently used keys (recommended for cache)
# volatile-lru — evict LRU among keys with TTL only
# allkeys-random — random eviction
# volatile-random — random among keys with TTL
# volatile-ttl — evict keys with shortest TTL first

# Persistence — for cache, you usually DON'T need persistence
# If Redis restarts, cache can be rebuilt from DB.
# disable persistence for better performance:
# save ""  # Disable RDB snapshots
# appendonly no  # Disable AOF

# But if you're using Redis for both cache AND other data
# (rate limiting counters, sessions), you may want persistence
# for the non-cache data.

# Connection settings
maxclients 10000  # Max simultaneous clients
timeout 300  # Close idle connections after 300s

# For production caching:
# - Use Redis with replication (1 master + N replicas)
# - Reads can go to replicas, writes go to master
# - Use connection pooling in your FastAPI app
# - Monitor memory usage and evictions (info memory command)
# - Set alerts on memory usage > 80%
```

## Common mistakes / gotchas

- **Caching non-deterministic results** — if a function returns different results for the same input (e.g., current time, random values), caching returns stale/incorrect results. Only cache deterministic functions.
- **Not setting TTL** — cached data lives forever in Redis. If the underlying data changes, the cache is stale forever. Always set TTL, even if long (24h, 7 days).
- **Cache key collisions** — if your cache key doesn't include all relevant parameters, different inputs return the same cached result. Include model version, all input parameters, and user context in the key.
- **Caching sensitive user data** — if you cache user-specific data with a key that doesn't include the user ID, one user might see another user's data. Always include user identity in cache keys for private data.
- **Cache stampede** — a popular cache entry expires and thousands of concurrent requests hit the DB. Use locking or probabilistic early expiration to prevent this.
- **Inconsistent cache invalidation** — updating the DB but forgetting to invalidate the cache leads to stale data. Use a systematic approach (versioned keys, write-through, or automatic invalidation in the data access layer).
- **Using Redis as both cache and queue without separation** — if you use the same Redis instance for caching and task queues (Celery), queue tasks can fill Redis memory and evict cached data. Use separate Redis instances or databases.
- **Not monitoring cache hit ratio** — if you don't track cache hit rate, you don't know if your caching is effective. A hit rate below 50% means caching isn't helping — maybe TTL is too short or access patterns are too scattered.

## Practice

> [!question]- Q1. Design a caching strategy for a FastAPI API that serves blog posts. The API has: (1) GET /posts/ (list, paginated), (2) GET /posts/{id} (single post), (3) POST /posts/ (create). Each post has comments. Design cache keys, TTLs, invalidation strategy, and cache stampede prevention.
**Answer:** 
```python
# Cache keys:
# post:list:{page}:{limit}:{sort}  — paginated list
# post:{id}  — single post (includes comments)
# post:{id}:version  — version number for invalidation

# TTLs:
# post:list: 300s (5 min) — lists change when posts are added
# post:{id}: 3600s (1h) — individual posts change less frequently
# post comments: 300s — comments may be added frequently

# Invalidation:
# On POST /posts/:
#   - Delete post:list:* keys (lists are stale)
#   - Increment version for the new post (if it has an ID)
# 
# On PUT /posts/{id}:
#   - Delete post:{id} key
#   - Increment post:{id}:version
#   - Delete post:list:* keys (lists may show updated post)
#
# On DELETE /posts/{id}:
#   - Delete post:{id}
#   - Delete post:list:* keys
#
# Cache stampede prevention:
# For popular posts (high traffic), use locking on cache miss.
# The first request to miss gets the lock, fetches from DB,
# populates cache. Other requests wait briefly and retry.
# For list endpoints, use probabilistic early expiration —
# if TTL < 20% remaining, 10% of requests trigger background refresh.
```
The key design: list caches are invalidated on any write (because the list may change). Individual post caches are invalidated only when that post changes. Versioned cache keys avoid race conditions between invalidation and cache reads. Short TTL for lists (frequent changes), longer TTL for individual posts (less frequent changes). Stampede prevention for high-traffic endpoints.

> [!question]- Q2. Your FastAPI API uses Redis for caching. The cache hit rate is only 30%. Diagnose possible causes and propose fixes.
**Answer:** Possible causes: (1) **TTL too short** — cache entries expire before they're re-requested. Fix: increase TTL based on access patterns (check how soon after a cache set the key is accessed again). (2) **Cache keys too specific** — too many unique keys, each accessed rarely. Fix: broaden cache keys (e.g., cache by category instead of by individual parameters). (3) **Access patterns are scattered** — long-tail access where most requests are for different resources. Fix: caching may not help — consider a different approach (database indexing, query optimization). (4) **Cache invalidation too aggressive** — cache is cleared more often than necessary. Fix: use versioned cache keys instead of explicit deletion, or increase TTL. (5) **Redis memory too small** — entries are evicted before being reused. Fix: increase Redis memory, adjust maxmemory-policy, or reduce TTL for less important data. (6) **Cache key bug** — cache keys don't match between set and get. Fix: audit cache key generation — ensure the same inputs produce the same keys. Diagnosis: check Redis INFO stats (keyspace_hits, keyspace_misses, evicted_keys). Check which keys are being evicted (slowlog or monitor). Profile access patterns — which endpoints have low hit rates. Fix based on evidence.

> [!question]- Q3. Compare HTTP caching (browser/CDN) vs server-side caching (Redis). When would you use each, and when would you use both?
**Answer:** HTTP caching: response is cached in the user's browser or a CDN edge server. Pros: zero server load for cached requests, lowest latency (served from edge), automatic (handled by browser/CDN). Cons: only works for public/shared data (can't cache user-specific data), limited control over invalidation, depends on client respecting headers. Best for: static assets, public API data, CDN-cached content. Server-side caching (Redis): response is cached on your server. Pros: works for any data (public or private), full control over invalidation and TTL, can cache partial results (DB query results, computation). Cons: still uses server resources (Redis), slightly higher latency than CDN. Best for: user-specific data, database query results, expensive computations, dynamic content that changes frequently. Use both: HTTP caching for public, infrequently-changing data (catalog, blog posts). Server-side caching for everything else (user data, query results, computation). For a public blog: CDN caches the HTML page (HTTP caching), Redis caches the database queries (server-side). The CDN handles 90% of traffic at the edge, Redis handles the remaining dynamic requests efficiently.

> [!question]- Q4. You have a FastAPI endpoint that returns a list of products filtered by category, price range, and sort order. The parameters can combine in thousands of ways. Design a caching strategy that doesn't explode Redis memory.
**Answer:** The problem: caching every possible combination of (category, price_range, sort, page) would create thousands of cache keys, most of which are rarely accessed. Solution: (1) **Cache only popular combinations** — track which parameter combinations are requested most frequently. Only cache combinations that are requested more than N times in a time window. Use a "cache warming" approach: first request doesn't cache, second request checks if it's been seen before, third request caches. (2) **Cache at the database level** — instead of caching the full API response, cache the database query results (product IDs for each filter combination). The API layer assembles the response from cached IDs. This is more memory-efficient because IDs are smaller than full product objects. (3) **Use a bounded cache** — set a max number of cache entries (e.g., 1000 most popular combinations). Use LRU eviction. When a new combination is requested and the cache is full, evict the least recently used entry. (4) **Cache by individual dimension** — cache products by category, by price range, separately. Then merge in memory. This reduces the total number of cache keys but requires merging logic. (5) **Short TTL for filter caches** — product filters change less frequently than individual products. Set TTL based on update frequency (e.g., 1 hour for category filters, 5 minutes for price range filters). The recommended approach: combine (1) cache only popular combinations with LRU eviction and (3) bounded cache size. This ensures Redis memory doesn't explode while still caching the most valuable queries.

> [!question]- Q5. A FastAPI API caches user profile data with a 1-hour TTL. A user updates their profile but doesn't see the change for up to an hour. Users complain. Design a solution that shows updates immediately without sacrificing cache performance.
**Answer:** The issue: TTL-based caching doesn't invalidate on write. Solutions: (1) **Write-through on update** — when a user updates their profile, update the cache at the same time as the DB. The cache always has the latest data. No staleness. But this adds write latency (must write to Redis). (2) **Versioned cache keys** — include a cache_version in the user record. On update, increment the version. The cache key includes the version: `user:{id}:{version}`. On update, the old cache key is still in Redis but never accessed. The next read uses the new version → cache miss → fresh data. Immediate consistency with no explicit invalidation. (3) **Explicit invalidation + short TTL fallback** — on update, delete the cache key. But if the delete fails (Redis down), the TTL ensures eventual consistency. Combine with write-through as primary, TTL as fallback. (4) **Hybrid approach** — on update, update the cache immediately (write-through) AND set a short TTL (5 minutes) as a safety net. If the cache update fails (Redis error), the short TTL limits staleness. If the cache update succeeds, the data is fresh immediately. The recommended approach: versioned cache keys (simple, no explicit invalidation, immediate consistency) combined with write-through for critical fields (email, name). Versioned keys handle the general case. Write-through ensures critical fields are always fresh.

## Related
[[rate-limiting]]
[[performance-profiling]]
[[request-response-lifecycle]]
[[inference-serving-patterns]]
[[system-design-for-apis-at-scale]]

#status/new