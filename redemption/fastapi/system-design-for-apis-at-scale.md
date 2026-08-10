# System Design for APIs at Scale

## What it is
System design for APIs at scale means designing an API that handles millions of requests per day, thousands of concurrent connections, low latency, high availability, and graceful degradation under load. This file covers the full stack: load balancing, horizontal scaling, database scaling (sharding, read replicas, connection pooling), caching strategies at scale, CDN, rate limiting at scale, circuit breakers, bulkheads, graceful degradation, and the trade-offs between consistency, availability, and partition tolerance (CAP theorem) as they apply to APIs.

## Why it matters
In interviews, system design is the final gate. They don't ask if you know syntax — they ask if you can design a system that works at scale. For your work — if your API ever gets popular, or if you're building something that needs to handle real traffic — the decisions you make early determine whether you can scale or need to rewrite everything. Understanding scale is what separates a developer from an engineer.

## Core example

### The scaling roadmap — from 1 to 10 million users

```
Stage 1 (1-1K users): Single server, monolith, SQLite/PostgreSQL
Stage 2 (1K-10K users): Load balancer + 2-4 app servers, read replicas, Redis cache
Stage 3 (10K-100K users): Horizontal scaling, sharding, CDN, message queues
Stage 4 (100K-1M users): Microservices (selective), multi-region, advanced caching
Stage 5 (1M+ users): Global distribution, edge computing, custom infrastructure
```

**The key insight**: don't over-engineer for scale you don't have. But design so that scaling is possible without rewriting. The decisions that matter early: database choice, API design, statelessness, and caching strategy.

### Load balancing — distributing traffic

```python
# Layer 4 (Transport) load balancing — TCP/UDP level
# Fast, low overhead, doesn't inspect HTTP content
# Examples: LVS, HAProxy in TCP mode, cloud load balancers (TCP)
# Use for: raw performance, non-HTTP protocols, SSL termination at backend

# Layer 7 (Application) load balancing — HTTP level
# Inspects HTTP headers, path, method, cookies
# Examples: nginx, HAProxy in HTTP mode, cloud ALB, Traefik
# Use for: path-based routing, header-based routing, SSL termination,
#          rate limiting, caching at the load balancer

# Load balancing algorithms:
# Round Robin — distribute requests in order (simple, fair)
# Least Connections — send to the server with fewest active connections
#                     (good for long-lived connections like WebSockets)
# IP Hash — same client IP goes to same server (session persistence)
#           but breaks if clients share IP (NAT, corporate networks)
# Weighted — assign weights to servers based on capacity
#            (newer/faster servers get more traffic)
# Least Response Time — send to server with fastest response time
#                       (requires health checks, most intelligent)

# Health checks — critical for load balancing
# Active: load balancer periodically probes each server
#         (GET /health/ready every 5s)
# Passive: load balancer monitors actual request responses
#          (if 5 consecutive 500s, mark server down)
# A server is removed from the pool if it fails health checks.
# When it passes again, it's gradually added back (slow start).

# Session persistence (sticky sessions):
# Some applications need the same client to go to the same server
# (e.g., in-memory session, WebSocket connections).
# Use: cookie-based persistence (load balancer sets a cookie),
# IP hash (same IP → same server), or source IP + port hash.
# But: sticky sessions reduce load balancing effectiveness and
# complicate scaling. Design stateless apps when possible.

# Nginx load balancing config:
# upstream fastapi_servers {
#     least_conn;  # Algorithm
#     server 10.0.0.1:8000 max_fails=3 fail_timeout=30s;
#     server 10.0.0.2:8000 max_fails=3 fail_timeout=30s;
#     server 10.0.0.3:8000 max_fails=3 fail_timeout=30s backup;  # Backup
#     
#     keepalive 32;  # Keep-alive connections to backend
# }
# 
# server {
#     location / {
#         proxy_pass http://fastapi_servers;
#         proxy_set_header Host $host;
#         proxy_set_header X-Real-IP $remote_addr;
#     }
# }
```

### Horizontal scaling — adding more servers

```python
# Horizontal scaling: add more server instances behind a load balancer.
# Vertical scaling: make a single server bigger (more CPU, RAM).
# Horizontal scaling is preferred for APIs — it's cheaper and has no upper limit.

# Key requirement for horizontal scaling: STATELESSNESS
# Each request can be handled by any server. No server-specific state.
# If you need state (sessions, cache, uploaded files), store it externally:
# - Sessions → Redis or database
# - Cache → Redis or Memcached (shared across instances)
# - Files → S3 or shared storage (not local disk)
# - Database connections → each instance has its own pool

# What makes an app NOT stateless:
# - In-memory session storage (use Redis)
# - Local file uploads (use S3)
# - In-memory cache (use Redis)
# - Server-specific configuration (use environment variables or config service)
# - Sticky sessions (avoid — redesign to be stateless)

# Auto-scaling: automatically add/remove servers based on load
# Metrics for scaling:
# - CPU utilization (> 70% → scale up)
# - Memory usage (> 80% → scale up)
# - Request latency (P99 > 500ms → scale up)
# - Queue depth (tasks waiting → scale up workers)
# - Error rate (> 1% → investigate, may scale up)

# Kubernetes Horizontal Pod Autoscaler (HPA):
# apiVersion: autoscaling/v2
# kind: HorizontalPodAutoscaler
# metadata:
#   name: fastapi-api
# spec:
#   scaleTargetRef:
#     apiVersion: apps/v1
#     kind: Deployment
#     name: fastapi-api
#   minReplicas: 2
#   maxReplicas: 10
#   metrics:
#     - type: Resource
#       resource:
#         name: cpu
#         target:
#           type: Utilization
#           averageUtilization: 70
#     - type: Resource
#       resource:
#         name: memory
#         target:
#           type: Utilization
#           averageUtilization: 80
#     - type: Pods
#       pods:
#         metric:
#           name: http_requests_per_second
#         target:
#           type: AverageValue
#           averageValue: 1000
```

### Database scaling — the bottleneck

```python
# The database is almost always the bottleneck at scale.
# API servers are easy to scale (stateless, add more).
# Databases are hard (stateful, shared data, consistency).

# Scaling strategy 1: Read replicas
# One master (write), multiple replicas (read).
# Writes go to master. Reads go to replicas.
# Replication is asynchronous (replicas lag behind master by seconds).

# FastAPI read/write splitting:
class DatabaseRouter:
    def __init__(self, master_url, replica_urls):
        self.master = create_engine(master_url)
        self.replicas = [create_engine(url) for url in replica_urls]
        self.replica_index = 0
    
    def get_read_db(self):
        # Round-robin across replicas
        db = self.replicas[self.replica_index]
        self.replica_index = (self.replica_index + 1) % len(self.replicas)
        return db
    
    def get_write_db(self):
        return self.master

# Usage:
# For read operations: db = router.get_read_db()
# For write operations: db = router.get_write_db()
# For operations that read-after-write: use master (replica lag)

# Pros: simple, improves read scalability
# Cons: replication lag (reads may be stale), writes still go to one server
# Best for: read-heavy workloads (90% reads, 10% writes)

# Scaling strategy 2: Sharding (horizontal partitioning)
# Split data across multiple databases based on a shard key.
# Common shard keys: user_id, geographic region, tenant_id.

# Example: user_id modulo N shards
def get_shard(user_id: int, num_shards: int) -> int:
    return user_id % num_shards

# Each shard is a separate database instance.
# Shard 0: users 0, N, 2N, 3N...
# Shard 1: users 1, N+1, 2N+1...

# Pros: unlimited horizontal scaling, each shard is independent
# Cons: complex (cross-shard queries are hard), rebalancing when adding
#       shards is painful, shard key choice is critical and hard to change
# Best for: very large datasets (> 1TB), high write throughput, multi-tenant

# Scaling strategy 3: Connection pooling
# Each API instance opens multiple database connections.
# Too many connections overwhelm the database.
# Connection pooling reuses connections across requests.

# PostgreSQL connection limits:
# Default: max_connections = 100
# Each API instance with pool_size=10 uses 10 connections.
# 10 API instances × 10 connections = 100 connections (maxed out!)
# Solution: use a connection pooler (PgBouncer) between API and DB.
# PgBouncer sits between API instances and PostgreSQL, managing
# a smaller pool of actual connections. API instances connect to
# PgBouncer, which multiplexes many API connections over fewer
# PostgreSQL connections.

# PgBouncer modes:
# Session mode: one DB connection per API connection (simple)
# Transaction mode: one DB connection per transaction (more efficient)
# Statement mode: one DB connection per statement (most efficient,
#                but breaks transactional features like PREPARE)

# Recommended: PgBouncer in transaction mode behind your API instances.
# This allows hundreds of API instances to share a few hundred DB
# connections, instead of each API instance needing its own pool.
```

### Caching at scale — multi-layer caching

```python
# Single-layer caching (just Redis) works for small scale.
# At scale, you need multi-layer caching:

# Layer 1: Client-side cache (browser, mobile app)
# Cache responses locally on the client.
# HTTP headers: Cache-Control, ETag, Last-Modified
# Pros: zero server load, fastest (no network)
# Cons: stale data, client-controlled

# Layer 2: CDN cache (edge servers)
# Cache responses at CDN edge servers (Cloudflare, CloudFront, Fastly).
# Close to users geographically.
# Pros: low latency (edge is close), reduces origin load
# Cons: only for public/cachable content, cache invalidation is slow

# Layer 3: Application cache (Redis/Memcached)
# Cache in a shared in-memory store.
# Pros: fast, shared across API instances, flexible
# Cons: network hop, cache invalidation complexity

# Layer 4: Database query cache (MySQL query cache, Redis for query results)
# Cache query results.
# Pros: reduces database load
# Cons: invalidation on data change, may not help with complex queries

# Layer 5: In-process cache (local cache in each API instance)
# Cache in the API process memory (e.g., functools.lru_cache, cachetools).
# Pros: fastest (no network), zero latency
# Cons: not shared across instances, memory usage per instance,
#       cache invalidation across instances is hard (use pub/sub)

# Multi-layer cache strategy:
# 1. Check client cache (304 Not Modified if valid)
# 2. Check CDN cache (serve from edge if valid)
# 3. Check Redis cache (serve if valid)
# 4. Check in-process cache (serve if valid)
# 5. Query database
# 6. Populate all caches (in-process → Redis → CDN → client)

# Cache invalidation at scale:
# When data changes, invalidate across all cache layers.
# In-process: use Redis pub/sub to notify all instances to invalidate.
# Redis: delete the key.
# CDN: purge the CDN cache (slow, takes minutes).
# Client: use short TTL or ETag validation.

# In-process cache with Redis pub/sub invalidation:
from cachetools import TTLCache
import redis.asyncio as redis

# Local cache per API instance (TTL 5 minutes)
local_cache = TTLCache(maxsize=1000, ttl=300)

# Redis pub/sub for invalidation
redis_client = redis.from_url(REDIS_URL)
pubsub = redis_client.pubsub()
await pubsub.subscribe("cache_invalidate")

async def listen_for_invalidation():
    async for message in pubsub.listen():
        if message["type"] == "message":
            key = message["data"].decode()
            local_cache.pop(key, None)  # Remove from local cache

# Start the listener as a background task
asyncio.create_task(listen_for_invalidation())

# When data changes:
async def update_data(key, value):
    await db.update(key, value)
    # Invalidate all caches
    await redis_client.delete(f"cache:{key}")  # Redis cache
    await redis_client.publish("cache_invalidate", key)  # Notify instances
    # CDN purge (async, slow)
    # aiohttp.post("https://cdn.example.com/purge", json={"key": key})
```

### Graceful degradation — surviving partial failures

```python
# At scale, things fail. Databases slow down, caches miss,
# external APIs timeout. Graceful degradation: the system
# continues to work (at reduced functionality) instead of
# completely failing.

# Circuit breaker pattern:
# When a downstream service fails repeatedly, stop calling it
# for a while. Fail fast instead of timing out.

class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.failures = 0
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
        self.last_failure_time = None
    
    async def execute(self, func, *args, **kwargs):
        if self.state == "OPEN":
            # If circuit is open, check if timeout has passed
            if datetime.utcnow() - self.last_failure_time > timedelta(seconds=self.timeout):
                self.state = "HALF_OPEN"  # Try again
            else:
                raise CircuitBreakerOpenError("Service unavailable")
        
        try:
            result = await func(*args, **kwargs)
            self.failures = 0
            self.state = "CLOSED"
            return result
        except Exception as e:
            self.failures += 1
            self.last_failure_time = datetime.utcnow()
            
            if self.failures >= self.failure_threshold:
                self.state = "OPEN"  # Open the circuit
            
            raise

# Usage:
db_breaker = CircuitBreaker(failure_threshold=3, timeout=30)
redis_breaker = CircuitBreaker(failure_threshold=5, timeout=10)

@app.get("/user/{user_id}")
async def get_user(user_id: int):
    try:
        # Try Redis first (with circuit breaker)
        user = await redis_breaker.execute(redis_client.get, f"user:{user_id}")
        if user:
            return json.loads(user)
    except CircuitBreakerOpenError:
        logger.warning("Redis circuit breaker open — falling back to DB")
    except Exception:
        pass  # Redis miss or error
    
    try:
        # Fall back to database (with circuit breaker)
        user = await db_breaker.execute(db.get_user, user_id)
        # Cache in Redis (best effort)
        try:
            await redis_client.setex(f"user:{user_id}", 3600, json.dumps(user))
        except:
            pass  # Don't fail if Redis is down
        return user
    except CircuitBreakerOpenError:
        # DB is also down — return cached/stale data if available
        stale = await redis_client.get(f"user:{user_id}:stale")
        if stale:
            return json.loads(stale)
        raise HTTPException(503, "Service temporarily unavailable")

# Bulkhead pattern:
# Isolate different parts of the system so that a failure in one
# part doesn't affect others. Like ship bulkheads — if one compartment
# floods, the ship doesn't sink.

# In FastAPI: separate thread pools for different operations.
# Database operations use one thread pool. External API calls use another.
# If the external API is slow and exhausts its thread pool, database
# operations continue unaffected.

from concurrent.futures import ThreadPoolExecutor

db_pool = ThreadPoolExecutor(max_workers=10)
external_api_pool = ThreadPoolExecutor(max_workers=5)
ml_inference_pool = ThreadPoolExecutor(max_workers=4)

# If ML inference is slow and uses all 4 threads, database and
# external API calls still have their own thread pools available.
# Without bulkheads, all operations share one pool and a slow
# operation can exhaust it, blocking everything.

# Rate limiting as graceful degradation:
# When under heavy load, rate limit aggressively to protect the system.
# Better to reject some requests (429) than to let all requests
# timeout (500) and crash the system.
```

### Multi-region deployment — global scale

```python
# For global users, deploy in multiple regions.
# Users in Europe connect to eu-west-1. Users in US connect to us-east-1.
# This reduces latency (users are closer to the server) and provides
# disaster recovery (if one region fails, others still work).

# Active-active: all regions serve traffic. Data is replicated
# between regions. Complex (conflict resolution) but best performance
# and availability.

# Active-passive: one region serves traffic. Others are on standby.
# Simpler but failover takes time and there's data loss during failover.

# Regional deployment pattern:
# Region 1 (us-east-1):
# - API servers (behind global load balancer)
# - Database (primary for US users)
# - Redis cache
# - Object storage (S3)

# Region 2 (eu-west-1):
# - API servers (behind global load balancer)
# - Database (replica of US primary, or sharded by region)
# - Redis cache
# - Object storage (S3)

# Global load balancer (CloudFront, Cloudflare, AWS Global Accelerator):
# Routes users to the nearest healthy region.
# If one region fails, routes all traffic to the other.

# Data replication challenges:
# - Write conflict: if the same user writes in two regions simultaneously
#   (unlikely but possible), which write wins? Use last-write-wins
#   (timestamp-based) or conflict-free replicated data types (CRDTs).
# - Replication lag: data written in one region takes time to appear
#   in another. Users may see stale data after switching regions.
# - Compliance: some data can't leave certain regions (GDPR, data
#   sovereignty). Use regional data storage with geo-fencing.

# For FastAPI multi-region:
# - Each region has its own FastAPI deployment (independent)
# - Database is either sharded by region or replicated asynchronously
# - CDN serves static content from edge locations
# - Session/Redis is regional (not global) — users stay in one region
# - Global load balancer routes based on latency and health

# Multi-region is complex. Don't do it unless you need it.
# Most APIs can start with single-region + CDN.
# Add multi-region when you have users in multiple continents
# or need disaster recovery.
```

## Common mistakes / gotchas

- **Scaling the app before the database** — adding more API servers when the database is the bottleneck makes it worse (more connections, more queries). Fix the database bottleneck first (indexing, caching, read replicas, connection pooling).
- **Not designing for statelessness early** — if your app stores sessions or uploads locally, you can't scale horizontally. Refactoring later is painful. Design statelessly from day one.
- **Over-sharding** — sharding adds massive complexity. Don't shard until you have to. Start with read replicas. Shard only when a single database can't handle the write load.
- **Ignoring connection limits** — each API instance opens database connections. 10 instances × 20 connections = 200 connections. If your DB max is 100, you're in trouble. Use PgBouncer or reduce pool size.
- **No circuit breakers** — if a downstream service fails, your API threads block waiting for timeouts. This cascades to your entire system. Use circuit breakers to fail fast.
- **Inconsistent caching** — cache in Redis but not in-process, or vice versa. Cache invalidation across layers is hard. Have a consistent strategy and implement invalidation for all layers.
- **Scaling based on CPU instead of latency** — CPU utilization is a lagging indicator. By the time CPU is high, latency is already bad. Scale based on latency (P99) and queue depth, not just CPU.
- **Not testing failure scenarios** — your system looks fine until something breaks. Test failure scenarios: kill a database replica, simulate network partition, test cache miss storms. Chaos engineering isn't just for big companies.

## Practice

> [!question]- Q1. Design a system for a FastAPI API that serves 1 million daily active users, handles 10,000 requests/second at peak, has a 99.9% uptime requirement, and serves users globally (US, Europe, Asia). Include the full architecture: load balancing, database, caching, CDN, scaling, and failure handling.
**Answer:** Architecture: (1) **Global load balancer**: CloudFront (AWS) or Cloudflare with latency-based routing. Users connect to the nearest edge location. (2) **Regional deployment**: 3 regions (us-east-1, eu-west-1, ap-southeast-1). Each region has: FastAPI behind Application Load Balancer (auto-scaling 2-20 instances), Redis cluster (3 nodes, sharded), PostgreSQL with 1 primary + 2 read replicas, S3 for file storage. (3) **Database**: primary in us-east-1, asynchronous read replicas in eu-west-1 and ap-southeast-1. Write operations route to US primary. Read operations go to local replica. For write-heavy regions, use sharding by region. (4) **Caching**: multi-layer — CDN (static assets, public API responses, 5-min TTL), Redis (shared cache, 1-min TTL for dynamic data), in-process (LRU cache, 30s TTL, invalidated via Redis pub/sub). (5) **Scaling**: auto-scale based on P99 latency (> 300ms → scale up) and CPU (> 70% → scale up). Min 2 instances per region (availability), max 20. (6) **Failure handling**: circuit breakers for DB and Redis (3 failures → open, 30s timeout). Graceful degradation: if Redis fails, serve from DB. If DB replica fails, route reads to primary. If region fails, global load balancer routes to other regions. (7) **Monitoring**: Prometheus + Grafana per region, centralized logging (ELK), distributed tracing (Jaeger), alert on P99 > 500ms, error rate > 0.1%, region health. (8) **Security**: WAF at CDN layer, rate limiting per region, JWT auth with regional key verification, TLS everywhere. Key design: global routing + regional isolation + multi-layer caching + automatic failover. The 99.9% uptime is achieved through redundancy (multiple instances per region, multiple regions), auto-scaling, and graceful degradation.

> [!question]- Q2. Your FastAPI API suddenly experiences a 100x traffic spike (from 100 req/s to 10,000 req/s). The database becomes the bottleneck and response times go from 50ms to 5 seconds. Describe your immediate response and long-term fixes.
**Answer:** Immediate (minutes): (1) **Enable aggressive caching** — if not already cached, cache all read responses in Redis with 5-minute TTL. This reduces database load by 80-90% for read-heavy traffic. (2) **Rate limiting** — implement per-user rate limiting (100 req/min). Reject excess requests with 429. This protects the database from being overwhelmed. (3) **Scale up API instances** — if auto-scaling isn't configured, manually add more API instances behind the load balancer. (4) **Database read replicas** — if not already using them, promote a standby to read replica and route read queries to it. This doubles read capacity. (5) **Circuit breakers** — if not already in place, add circuit breakers for database calls. If the DB is slow, fail fast and return cached/stale data instead of timing out. (6) **Disable non-essential features** — turn off expensive features (analytics, exports, real-time updates) to conserve database capacity. Long-term (days/weeks): (1) **Implement proper auto-scaling** — based on latency and CPU, not manual. (2) **Database optimization** — add indexes, optimize slow queries, implement connection pooling (PgBouncer). (3) **Multi-layer caching** — CDN for public data, Redis for shared cache, in-process for hot data. (4) **Database sharding** — if a single DB can't handle writes, shard by user ID or region. (5) **Read/write separation** — route all reads to replicas, writes to primary. (6) **Async processing** — move non-critical operations (notifications, analytics, exports) to background workers. (7) **Load testing** — regularly test with 10x expected traffic to find bottlenecks before they become incidents. The key: immediate response is about survival (cache, rate limit, scale). Long-term fixes are about resilience (architecture, automation, testing).

> [!question]- Q3. Explain the CAP theorem and its practical implications for a FastAPI API with a distributed database. If you have to choose between consistency and availability during a network partition, what do you pick and why?
**Answer:** CAP theorem: in a distributed system, you can only guarantee two of three properties during a network partition: Consistency (all nodes see the same data at the same time), Availability (every request receives a response, even if some nodes are down), Partition tolerance (the system continues to operate despite network partitions). During a network partition (nodes can't communicate), you must choose between consistency and availability. CP (Consistency + Partition tolerance): if nodes can't communicate, reject writes (or reads) to avoid inconsistency. The system is unavailable for some operations. AP (Availability + Partition tolerance): if nodes can't communicate, continue serving requests from each node. The system is available but may return inconsistent data (different nodes have different data). For a FastAPI API: most user-facing APIs choose AP (availability). Users prefer a slightly stale response over an error. E.g., a social media feed can show slightly old posts but shouldn't error. A banking API chooses CP (consistency). You can't have inconsistent account balances. The trade-off: CP systems reject requests during partitions (503 errors). AP systems serve potentially stale data (200 with stale data). Practical recommendation: for most APIs, choose AP with eventual consistency. Use quorum reads/writes (R + W > N) to balance consistency and availability. For critical operations (payments, auth), use CP with explicit error handling. The key: CAP is about what happens during partitions, not normal operation. During normal operation, you can have all three. The choice only matters when the network splits.

> [!question]- Q4. A FastAPI API uses Redis for caching and session storage. Redis suddenly becomes slow (500ms response time instead of 1ms). The API latency spikes from 50ms to 1 second. Diagnose and fix without restarting Redis.
**Answer:** Diagnosis: (1) Check Redis info — `INFO memory` (memory usage near max? evictions?), `INFO stats` (keys missed ratio, connected clients), `INFO cpu` (CPU usage). (2) Check slow log — `SLOWLOG GET` to see which commands are slow. (3) Check for big keys — a single large key can block Redis (single-threaded). (4) Check for memory fragmentation — high fragmentation ratio causes performance issues. (5) Check connected clients — too many connections can overwhelm Redis. Fixes without restart: (1) **Memory pressure** — if near maxmemory, evict keys (`redis-cli --scan --pattern "cache:*" | head -100 | xargs redis-cli DEL` to manually delete non-critical keys). Or increase maxmemory if possible. (2) **Big keys** — find and delete big keys (`redis-cli --bigkeys`). Or break them into smaller keys. (3) **Slow commands** — avoid KEYS, FLUSHDB, HGETALL on large hashes in production. Use SCAN instead of KEYS. (4) **Connection pool** — if too many connections, reduce the connection pool size in FastAPI. Use Redis connection pooling. (5) **Persistence** — if RDB snapshot is running (BGSAVE), it can cause latency spikes. Schedule snapshots during off-peak or switch to AOF with everysec. (6) **Read replicas** — if using Redis Sentinel/Cluster, route reads to replicas to reduce load on primary. (7) **Bypass Redis temporarily** — if Redis is critically slow, add a circuit breaker that bypasses Redis and serves directly from DB (with degraded performance but functional). The key: Redis is single-threaded — one slow command blocks everything. Find the slow command or memory pressure, fix it, and add circuit breakers to prevent future cascading failures.

> [!question]- Q5. Design a rate limiting strategy for a FastAPI API that serves free users (100 req/hour), pro users (1000 req/hour), and enterprise users (unlimited but with fair usage). The API has 10 server instances behind a load balancer. Rate limiting must be accurate across all instances.
**Answer:** Use Redis-based distributed rate limiting (not in-memory, since there are 10 instances). The design: (1) **Key structure** — `rate_limit:{user_id}:{hour_window}` where hour_window = current_hour_timestamp. (2) **Algorithm** — sliding window counter (not fixed window, to avoid the 2x limit at window boundaries). Store current hour count and previous hour count. Calculate weighted count based on time elapsed in the current window. (3) **Redis Lua script** — atomic increment and check to prevent race conditions between instances. All 10 instances run the same script on the same Redis key. (4) **Tier-based limits** — free: 100/hour, pro: 1000/hour, enterprise: 10000/hour (fair usage, not truly unlimited). Store user tier in Redis or JWT claims. (5) **Middleware order** — rate limiting middleware runs early (after CORS, before auth) to reject rate-limited requests before expensive auth computation. (6) **Headers** — include X-RateLimit-Limit, X-RateLimit-Remaining, X-RateLimit-Reset, and Retry-After (on 429) in every response. (7) **IP-based fallback** — for unauthenticated endpoints, rate limit by IP address as a fallback. (8) **Burst allowance** — allow 2x the normal rate for 1 minute (token bucket) to handle legitimate bursts. (9) **Monitoring** — track rate limit hits per tier. If a tier has many 429s, consider increasing the limit or notifying the user. (10) **Redis fail-open** — if Redis is unavailable, fail open (allow requests) with alerting. Rate limiting is important but availability is more important. The key: Redis provides the shared state across all 10 instances. The sliding window counter provides accuracy. Lua scripts provide atomicity. Tier-based limits provide differentiation. Headers provide transparency.

## Related
[[rate-limiting]]
[[caching]]
[[deployment-docker-uvicorn]]
[[logging-and-monitoring]]
[[background-workers-queues]]
[[inference-serving-patterns]]
[[cors-and-security-headers]]
[[middleware]]

#status/new