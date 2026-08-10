# Database Integration — Async ORM

## What it is
Async database access in FastAPI means using async database drivers and ORMs that release the event loop during I/O, instead of blocking threads. The key options: SQLAlchemy 2.0 with async mode (asyncio driver), TortoiseORM (designed for async), Prisma (Python client with async support), and raw async drivers like asyncpg (PostgreSQL) and aiomysql (MySQL). This file covers the async ORM pattern, session management per request, the gotchas that break async DB code, and when to use raw SQL vs ORM.

## Why it matters
Database access is the most common I/O operation in APIs. Using a sync DB driver in an async endpoint blocks the event loop (as covered in [[async-endpoints-when-to-use]]), silently serializing requests. Async DB access is the foundation of high-concurrency FastAPI APIs. In interviews, async DB questions test whether you understand connection pooling, session scoping, and the difference between async and sync ORM patterns. For your work — any API that serves data — this is non-negotiable.

## Core example

### SQLAlchemy 2.0 async — the most common pattern

```python
from sqlalchemy.ext.asyncio import (
    create_async_engine, AsyncSession, async_sessionmaker
)
from sqlalchemy.orm import declarative_base

# Async engine — uses asyncpg for PostgreSQL
# The URL uses the async driver prefix: postgresql+asyncpg://
engine = create_async_engine(
    "postgresql+asyncpg://user:pass@localhost/dbname",
    echo=True,  # Log SQL queries (disable in production)
    pool_size=10,  # Connection pool size
    max_overflow=20,  # Extra connections beyond pool_size
    pool_timeout=30,  # Wait for connection from pool
)

# Async session factory — creates sessions per request
AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

# Base model class
Base = declarative_base()

# The dependency pattern — one session per request:
from fastapi import Depends

async def get_db():
    """Create a DB session for this request, close on completion"""
    async with AsyncSessionLocal() as session:
        yield session
        # Session is automatically closed when exiting the async context
        # No need to explicitly close — the async context manager handles it

# Model definition:
from sqlalchemy import Column, Integer, String, DateTime
from datetime import datetime

class User(BaseModel):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    name = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

# CRUD operations with async:
async def get_user(db: AsyncSession, user_id: int):
    result = await db.get(User, user_id)  # Single object by PK
    return result

async def get_users(db: AsyncSession, skip: int = 0, limit: int = 10):
    result = await db.execute(
        select(User).offset(skip).limit(limit)
    )
    return result.scalars().all()  # Extract models from result

async def create_user(db: AsyncSession, user: UserCreate):
    db_user = User(**user.model_dump())
    db.add(db_user)
    await db.commit()  # Must await commit
    await db.refresh(db_user)  # Refresh to get auto-generated fields
    return db_user

# In endpoint:
@app.get("/users/{user_id}", response_model=User)
async def get_user_endpoint(user_id: int, db: AsyncSession = Depends(get_db)):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    return user

@app.post("/users/", response_model=User, status_code=201)
async def create_user_endpoint(user: UserCreate, db: AsyncSession = Depends(get_db)):
    db_user = await create_user(db, user)
    return db_user
```

### The critical async ORM gotchas

```python
# GOTCHA 1: Using sync session in async context
# DON'T:
session = Session()  # Sync session
user = session.get(User, 1)  # Blocks the event loop!

# DO:
async with AsyncSessionLocal() as session:
    user = await session.get(User, 1)  # Async, non-blocking

# GOTCHA 2: Forgetting await on commit/refresh
# DON'T:
await db.add(user)
db.commit()  # Sync commit — blocks
db.refresh(user)  # Sync refresh — blocks

# DO:
db.add(user)
await db.commit()  # Must await
await db.refresh(user)  # Must await

# GOTCHA 3: Using ORM relationships without eager loading
# The N+1 query problem in async is worse because each query
# is a separate event loop yield.

class User(Base):
    posts = relationship("Post", back_populates="author")

# DON'T — N+1 queries:
users = await db.execute(select(User))
for user in users.scalars():
    # Each iteration triggers a separate query for posts
    print(user.posts)  # N+1 queries!

# DO — eager load:
result = await db.execute(
    select(User).options(selectinload(User.posts))
)
users = result.scalars().all()
# Now user.posts is loaded — 2 queries total (users + posts)

# GOTCHA 4: Closing session before accessing relationships
# Lazy loading doesn't work with async sessions after they're closed.

# DON'T:
async def get_user_with_posts(user_id: int):
    async with AsyncSessionLocal() as session:
        user = await session.get(User, user_id)
        # Session closes when exiting context
    return user  # user.posts will fail — session closed, no lazy load

# DO:
async def get_user_with_posts(user_id: int):
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).options(selectinload(User.posts))
            .where(User.id == user_id)
        )
        user = result.scalars().first()
        # Access posts while session is open
        posts = user.posts  # Works — loaded eagerly
    return user  # Returns with posts already loaded

# Or use a Pydantic model that extracts data before closing:
async def get_user(user_id: int):
    async with AsyncSessionLocal() as session:
        user = await session.get(User, user_id)
        return UserSchema.model_validate(user)  # Extract data
        # Data is extracted before session closes
```

### Connection pooling — why it matters and how to configure

```python
# Database connections are expensive to create (TCP + auth + state).
# Connection pooling reuses connections across requests.

# SQLAlchemy async engine pool configuration:
engine = create_async_engine(
    DATABASE_URL,
    pool_size=10,       # Keep 10 connections open always
    max_overflow=20,    # Allow up to 30 total during peak
    pool_timeout=30,    # Wait 30s for a connection before raising
    pool_recycle=1800,  # Recycle connections after 30min (avoid stale)
    echo_pool=True,     # Log pool events (debug)
)

# Pool behavior:
# - pool_size: minimum connections kept open
# - When all pool_size connections are in use, new requests
#   borrow from overflow (up to max_overflow)
# - If pool is exhausted (max_overflow reached), requests wait
#   up to pool_timeout seconds, then raise TimeoutError
# - pool_recycle: close connections after this many seconds
#   (important for cloud DBs that drop idle connections)

# Monitoring pool usage:
# Check pool status:
print(engine.pool.status())
# Shows: pool size, checked out connections, overflow, etc.

# For production: set pool_size based on your DB's max_connections
# and number of app instances. If DB max_connections = 100 and
# you have 4 app instances, pool_size should be ≤ 20 per instance.
# Leave room for admin connections and other services.
```

### Raw async driver vs ORM — when to use each

```python
# ORMs are convenient but have overhead. For complex queries or
# performance-critical code, raw SQL with an async driver is better.

# Raw asyncpg (PostgreSQL):
import asyncpg

async def get_user_raw(user_id: int):
    conn = await asyncpg.connect(DATABASE_URL)
    row = await conn.fetchrow(
        "SELECT * FROM users WHERE $1", user_id
    )
    await conn.close()
    return row

# With connection pooling (recommended):
pool = None

async def init_pool():
    global pool
    pool = await asyncpg.create_pool(
        DATABASE_URL, min_size=5, max_size=20
    )

async def get_user_pooled(user_id: int):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
    return row
    # Connection returned to pool after use

# Comparison:
# ORM advantages:
# - Automatic schema mapping, relationship loading, migrations
# - Type safety, query building, connection management
# - Less boilerplate for CRUD

# ORM disadvantages:
# - Overhead for simple queries (ORM generates SQL)
# - N+1 query problem (eager loading needed)
# - Complex queries are harder to write and optimize
# - Less control over exact SQL generated

# Raw driver advantages:
# - Full control over SQL — optimize queries precisely
# - Less overhead — no ORM layer
# - Better for complex aggregations, window functions, etc.
# - asyncpg is the fastest PostgreSQL driver (written in C)

# Raw driver disadvantages:
# - Manual connection management (need pooling)
# - Manual result-to-object mapping
# - No relationship loading — you write joins manually
# - More boilerplate

# Recommendation:
# - Use ORM for CRUD-heavy applications with standard queries
# - Use raw asyncpg for complex queries, analytics, or performance-critical paths
# - Mix both in the same app — ORM for 80% of queries, raw for the 20% that need optimization
```

### Transaction management in async

```python
# In async SQLAlchemy, transactions are managed with begin()

async def transfer_money(db: AsyncSession, from_id: int, to_id: int, amount: float):
    async with db.begin():  # Starts a transaction
        from_account = await db.get(Account, from_id)
        to_account = await db.get(Account, to_id)
        
        if from_account.balance < amount:
            raise HTTPException(400, "Insufficient funds")
        
        from_account.balance -= amount
        to_account.balance += amount
        
        # Transaction commits automatically when exiting the context
        # If an exception is raised, transaction rolls back
    
    # Alternative: explicit transaction
    async with db.begin():
        # ... operations ...
        # If no exception → commit
        # If exception → rollback (automatic)

# For nested transactions (savepoints):
async with db.begin():
    # Outer transaction
    async with db.begin_nested():
        # Inner savepoint
        try:
            # ... operations that might fail ...
        except:
            # Inner transaction rolls back, outer continues
            pass
    
    # If inner rolled back, outer can still commit or rollback
    # Savepoints are useful for partial failures within a larger transaction
```

### Database migrations with async

```python
# Alembic is the standard migration tool for SQLAlchemy.
# With async, you need to configure Alembic to use async engine.

# alembic/env.py — configure for async:
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.engine import Connection

# Get the async engine
connectable = create_async_engine(config.get_main_option("sqlalchemy.url"))

# For Alembic's run_migrations_online, use a sync connection wrapper:
def run_migrations_online():
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=Base.metadata,
        )
        with context.begin_transaction():
            context.run_migrations()

# The key: Alembic itself doesn't support async migrations directly.
# You create an async engine but get a sync connection from it
# for Alembic. The migrations run synchronously — they're a one-time
# operation during deployment, not performance-critical.

# Alternative: use TortoiseORM with built-in async migrations
# tortoise generate_schemas() or tortoise run-migrations
# This is fully async but less mature than Alembic.
```

## Common mistakes / gotchas

- **Using sync Session instead of AsyncSession** — the most common mistake. Even if the endpoint is async, using the sync Session class blocks the event loop. Always use `AsyncSession` and `create_async_engine`.
- **Forgetting `await` on `commit()` and `refresh()`** — these are async methods on AsyncSession. Forgetting await makes them no-ops or causes errors. Always `await db.commit()` and `await db.refresh()`.
- **Lazy loading with closed session** — async sessions don't support lazy loading after the session closes. Either eager-load relationships with `selectinload` or extract data before closing the session.
- **Not using connection pool** — creating a new connection per request is slow and exhausts DB connections. Always use connection pooling (SQLAlchemy's built-in pool or asyncpg pool).
- **Sharing session across requests** — the session should be created per request (via dependency with yield) and closed when the response ends. Sharing a session across requests causes data inconsistency and memory leaks.
- **N+1 queries in async** — each query in an async loop yields to the event loop, making N+1 particularly bad. Always use `selectinload` or `joinedload` for relationships.
- **Mixing sync and async ORM in the same codebase** — possible but confusing. Pick one approach per service. If you need both, isolate them in separate modules with clear boundaries.

## Practice

> [!question]- Q1. A FastAPI endpoint with async SQLAlchemy returns a User object with a `posts` relationship. The endpoint works but when the client receives the response, the posts field is empty or causes an error. Diagnose and fix.
**Answer:** This is the lazy loading + closed session problem. The async session closes when the endpoint returns (after the `yield` in the dependency), but Pydantic serialization happens after the session closes. When Pydantic tries to access `user.posts`, the session is closed and lazy loading fails. Fix: (1) Eager-load the relationship: `result = await db.execute(select(User).options(selectinload(User.posts)).where(...))`. (2) Or extract the data before returning: use a Pydantic model with `model_validate()` while the session is still open (inside the `with` block of the dependency). (3) Or use a serializer function that loads all needed data before returning. The recommended approach: eager-load with `selectinload` in the query, so the data is available before serialization.

> [!question]- Q2. Your FastAPI API uses async PostgreSQL. Under load, you see "PoolTimeout: Queue limit reached" errors. Explain what's happening and how to fix.
**Answer:** The connection pool has reached its maximum capacity (pool_size + max_overflow). All connections are in use, and new requests are waiting for a connection. After pool_timeout seconds, they raise PoolTimeout. Causes: (1) pool_size is too small for the concurrency level. (2) Connections are not being returned to the pool (session not closed properly). (3) Long-running queries hold connections too many. (4) Connection leak — sessions not closed after use. Fixes: (1) Increase pool_size and max_overflow based on DB capacity. (2) Ensure sessions are properly closed (use async context manager with yield). (3) Optimize long-running queries. (4) Set pool_recycle to avoid stale connections. (5) Add connection pooling monitoring to detect leaks. (6) Use read replicas to distribute read queries. The key: monitor pool utilization (checked-out connections vs pool size) and tune based on actual usage patterns, not guesses.

> [!question]- Q3. Compare the async SQLAlchemy pattern with the TortoiseORM pattern. When would you choose each?
**Answer:** async SQLAlchemy: uses the same SQLAlchemy you know but with async drivers. Mature, well-documented, Alembic migrations, large ecosystem. But requires careful session management and has async-specific gotchas (lazy loading, commit/refresh must be awaited). Best for: teams familiar with SQLAlchemy, existing SQLAlchemy projects migrating to async, complex queries needing SQLAlchemy's full power. TortoiseORM: designed from scratch for async. Django-like ORM syntax, built-in async migrations, auto-generates schemas. Simpler for basic CRUD. But less mature, smaller community, fewer advanced features. Best for: new async-first projects, teams coming from Django, simpler data models, when you want built-in async migrations without Alembic config. For production APIs at scale: async SQLAlchemy is the safer choice (maturity, ecosystem, Alembic). For rapid prototyping or Django-like experience: TortoiseORM.

> [!question]- Q4. You need to implement a "bulk insert" of 10,000 records. The naive approach (looping `db.add()` 10,000 times) is too slow. Design the optimized approach.
**Answer:** The naive approach creates 10,000 individual INSERT statements — slow due to round-trip overhead and ORM overhead. Optimized approaches: (1) **bulk_save_objects** (SQLAlchemy): `await db.bulk_save_objects(list_of_objects)` — batches inserts into fewer statements. Still has some ORM overhead. (2) **bulk_insert_mappings**: `await db.bulk_insert_mappings(User, list_of_dicts)` — lower overhead, skips ORM identity map. Faster than bulk_save_objects. (3) **execute with values()**: `await db.execute(insert(User).values(list_of_dicts))` — Core-level bulk insert, minimal overhead. Fastest SQLAlchemy approach. (4) **asyncpg copy_records_to_table**: For maximum speed, use asyncpg's COPY protocol — loads data directly into PostgreSQL at near-native speed. 10-100x faster than individual inserts. For 10,000 records: use `execute(insert().values())` for a good balance of speed and ORM compatibility. For 1M+ records: use asyncpg copy. The key insight: bulk operations bypass the ORM's per-object overhead. Choose the method based on data size and whether you need ORM features (relationships, validation) for the inserted objects.

> [!question]- Q5. Design a database connection strategy for a FastAPI application that needs to support multiple tenants (each tenant has a separate database). The connection should be selected per request based on the tenant ID in the request.
**Answer:** Use a connection routing pattern with a dynamic session factory:
```python
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

# Pre-create engines for known tenants, or create on-demand
engines = {}

def get_engine(tenant_id: str):
    if tenant_id not in engines:
        url = f"postgresql+asyncpg://{tenant_id}_user:pass@localhost/{tenant_id}_db"
        engines[tenant_id] = create_async_engine(url, pool_size=5)
    return engines[tenant_id]

async def get_db(tenant_id: str = Depends(get_tenant_id)):
    engine = get_engine(tenant_id)
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with AsyncSessionLocal() as session:
        yield session

# The tenant_id is extracted from the request (header, subdomain, JWT claim)
# Each tenant gets its own engine with its own connection pool.
# The pool size per tenant is smaller since not all tenants are active simultaneously.
# For many tenants: use a connection pool per tenant with lazy creation
# and idle timeout to release unused connections.
# Alternative: shared database with schema-per-tenant — uses a single
# connection pool but switches schemas per request (SET search_path).
# This is more connection-efficient but less isolated.
```
The key design: each tenant has a separate database (full isolation) with its own connection pool. The pool is created on-demand and cached. For many tenants, use idle timeout to release unused connections. The alternative (shared DB, separate schemas) uses one connection pool but provides less isolation. Choose based on isolation requirements and tenant count.

## Related
[[async-await-and-event-loop]]
[[async-endpoints-when-to-use]]
[[dependency-injection]]
[[project-folder-structure]]
[[error-handling-and-exception-handlers]]

#status/new