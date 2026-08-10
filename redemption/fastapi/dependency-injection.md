# Dependency Injection

## What it is
FastAPI's dependency injection (DI) system lets you declare reusable components (database connections, auth checks, pagination params, current user) that are automatically resolved and injected into endpoint functions. Dependencies are declared with `Depends()`, can be synchronous or async, can yield values for cleanup (like context managers), and can form dependency graphs (dependencies that depend on other dependencies). The DI system is what makes FastAPI code clean, testable, and DRY — instead of repeating auth checks or DB session creation in every endpoint, you declare them once as dependencies.

## Why it matters
Dependency injection is the architectural backbone of FastAPI applications. Without it, every endpoint repeats the same setup code (get DB, check auth, validate params). With it, you get clean separation of concerns, reusable components, and testability (swap dependencies in tests). In interviews, DI questions test whether you understand the resolution order, async vs sync dependencies, and the yield pattern for cleanup. For your work — building APIs with auth, database access, and shared logic — DI is the pattern that keeps your code from becoming a spaghetti of repeated setup code.

## Core example

### Basic dependency — the simplest case

```python
from fastapi import FastAPI, Depends, HTTPException
from typing import Annotated

app = FastAPI()

# A dependency is just a function that returns a value
def get_token(x: str = Header(...)):
    if x != "secret-token":
        raise HTTPException(status_code=400, detail="Invalid token")
    return x

@app.get("/items/")
async def list_items(token: str = Depends(get_token)):
    # The dependency is called before the endpoint runs
    # If it raises HTTPException, the endpoint is never called
    # The return value is injected into the endpoint parameter
    return {"items": [], "token": token}

# Dependencies can have their own dependencies:
def get_current_user(token: str = Depends(get_token)):
    if token != "secret-token":
        raise HTTPException(status_code=401, detail="Unauthorized")
    return {"username": "admin", "role": "admin"}

@app.get("/users/me")
async def get_me(user: dict = Depends(get_current_user)):
    return user

# The resolution order: get_token → get_current_user → endpoint
# Dependencies are resolved depth-first, left-to-right.
# If get_token fails, get_current_user is never called.
```

### Async dependencies — when you need I/O

```python
from fastapi import Depends
import asyncio

# Dependencies can be async — FastAPI awaits them just like async endpoints
async def get_async_data():
    await asyncio.sleep(1)  # Simulate I/O
    return {"data": "from async dependency"}

@app.get("/async-dep/")
async def endpoint(data: dict = Depends(get_async_data)):
    return data

# Mix of sync and async dependencies:
def sync_dep():
    return "sync"

async def async_dep():
    return "async"

@app.get("/mixed/")
async def mixed(
    s: str = Depends(sync_dep),
    a: str = Depends(async_dep),
):
    return {"sync": s, "async": a}

# FastAPI handles both: sync deps are called directly, async deps are awaited.
# The resolution order is preserved regardless of sync/async.
# For performance: prefer async dependencies for I/O-bound work
# (DB queries, API calls) so they don't block the event loop.
# Use sync dependencies for fast, in-memory operations.
```

### The yield pattern — cleanup like a context manager

```python
from fastapi import Depends
from contextlib import contextmanager

# Dependencies that need cleanup (DB sessions, file handles, network connections)
# use the yield pattern — like a context manager.

def get_db():
    db = connect_to_database()  # Setup
    try:
        yield db  # Yield to the endpoint
    finally:
        db.close()  # Cleanup — runs even if endpoint raises

# Async version:
async def get_async_db():
    db = await connect_to_database()
    try:
        yield db
    finally:
        await db.close()

@app.get("/items/")
async def list_items(db = Depends(get_db)):
    # db is available here
    items = db.query("SELECT * FROM items")
    # If an exception is raised here, the finally block still runs
    return {"items": items}

# The yield pattern is the FastAPI equivalent of a context manager.
# Code before yield = __enter__, code after yield = __exit__.
# The cleanup runs in all cases:
# - Endpoint returns normally → cleanup runs
# - Endpoint raises HTTPException → cleanup runs
# - Endpoint raises unhandled exception → cleanup runs (then 500 returned)

# Multiple yields are NOT allowed — a dependency yields exactly once.
# If you need multiple setup/teardown pairs, use nested dependencies
# or separate dependencies.

# Dependencies with yield can also have dependencies themselves:
def get_config():
    return load_config()

def get_db_with_config(config = Depends(get_config)):
    db = connect(config.database_url)
    try:
        yield db
    finally:
        db.close()
```

### Dependency graphs — composing dependencies

```python
# Dependencies can depend on other dependencies, forming a graph.
# FastAPI resolves them in topological order (dependencies first).

def get_query_params(skip: int = 0, limit: int = 10):
    return {"skip": skip, "limit": limit}

def get_current_user(token: str = Depends(get_token)):
    return verify_token(token)

def get_authorized_user(
    user: dict = Depends(get_current_user),
    params: dict = Depends(get_query_params),
):
    if user["role"] != "admin":
        raise HTTPException(403, "Admin only")
    return {"user": user, "params": params}

@app.get("/admin/")
async def admin_panel(data: dict = Depends(get_authorized_user)):
    # data = {"user": {...}, "params": {...}}
    return data

# Resolution order:
# 1. get_token (no deps)
# 2. get_current_user (depends on get_token)
# 3. get_query_params (no deps)
# 4. get_authorized_user (depends on get_current_user, get_query_params)
# 5. admin_panel endpoint

# FastAPI builds a dependency graph and resolves in the correct order.
# Circular dependencies are detected and raise an error at startup.
# This is the key to building modular, reusable authentication and
# authorization logic — each layer is a dependency that can be reused
# across endpoints.
```

### Class-based dependencies — stateful dependencies

```python
from fastapi import Depends

# Dependencies can be classes — useful for stateful components.
# The class must be callable (__call__) or FastAPI treats it as
# a dependency that instantiates the class.

class Paginator:
    def __init__(self, page: int = 1, page_size: int = 10):
        self.page = page
        self.page_size = page_size
    
    def offset(self) -> int:
        return (self.page - 1) * self.page_size
    
    def limit(self) -> int:
        return self.page_size

# Usage — FastAPI instantiates the class with query params:
@app.get("/items/")
async def list_items(paginator: Paginator = Depends(Paginator)):
    # Paginator is instantiated with page and page_size from query params
    # because the __init__ parameters match query parameter names
    offset = paginator.offset()
    limit = paginator.limit()
    return {"items": get_items(offset, limit), "page": paginator.page}

# Class-based dependencies are useful when:
# - You need to maintain state across the dependency's lifetime
# - You have multiple related parameters that belong together
# - You want to reuse the dependency logic across multiple endpoints
# - You need methods on the dependency (not just a return value)

# For simple cases, function-based dependencies are cleaner.
# For complex, stateful, or reusable components, class-based is better.
```

### Dependency overrides — the key to testability

```python
# The most powerful feature of FastAPI's DI: you can override dependencies
# in tests. This lets you replace real DB connections with test databases,
# real auth with mock users, and external APIs with stubs.

# app.dependency_overrides[original_dep] = override_dep

# In production:
def get_db():
    return connect_to_production_db()

def get_current_user(token: str = Depends(get_token)):
    return verify_production_token(token)

# In tests:
from fastapi.testclient import TestClient

test_db = TestDatabase()
test_user = {"username": "test", "role": "admin"}

def override_get_db():
    return test_db

def override_get_current_user():
    return test_user

# Apply overrides:
app.dependency_overrides[get_db] = override_get_db
app.dependency_overrides[get_current_user] = override_get_current_user

client = TestClient(app)
response = client.get("/items/")
# Uses test_db and test_user — no real DB, no real auth

# Clean up after tests:
app.dependency_overrides.clear()

# Or use a context manager for automatic cleanup:
from contextlib import contextmanager

@contextmanager
def override_dependencies():
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    try:
        yield
    finally:
        app.dependency_overrides.clear()

# Usage:
# with override_dependencies():
#     response = client.get("/items/")
#     # Overrides active
# # Overrides cleared automatically

# This is the standard testing pattern for FastAPI applications.
# Without dependency overrides, you'd need to spin up a real DB and
# create real users for every test — slow and fragile. With overrides,
# tests are fast, isolated, and deterministic.
```

### Security patterns with dependencies

```python
from fastapi import Depends, HTTPException, Security
from fastapi.security import OAuth2PasswordBearer, APIKeyHeader

# OAuth2 bearer token:
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/token")

async def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        username = payload.get("sub")
        if username is None:
            raise HTTPException(401, "Invalid token")
        return await get_user_by_username(username)
    except JWTError:
        raise HTTPException(401, "Invalid token")

async def get_active_user(current_user: User = Depends(get_current_user)):
    if not current_user.is_active:
        raise HTTPException(403, "Inactive user")
    return current_user

async def get_admin_user(current_user: User = Depends(get_active_user)):
    if current_user.role != "admin":
        raise HTTPException(403, "Admin only")
    return current_user

# Usage in endpoints:
@app.get("/users/me")
async def read_users_me(current_user: User = Depends(get_current_user)):
    return current_user

@app.get("/admin/")
async def admin_panel(admin: User = Depends(get_admin_user)):
    return {"message": "admin panel"}

# API key in header:
api_key_header = APIKeyHeader(name="X-API-Key")

def verify_api_key(api_key: str = Security(api_key_header)):
    if api_key != EXPECTED_API_KEY:
        raise HTTPException(401, "Invalid API key")
    return api_key

# Security() is like Depends() but with additional security scheme
# integration for OpenAPI docs. It shows the auth requirement in
# the generated API documentation.

# The pattern: chain dependencies for layered security.
# get_current_user → get_active_user → get_admin_user
# Each layer adds a requirement. Endpoints use the appropriate
# level of dependency based on their access requirements.
```

## Common mistakes / gotchas

- **Forgetting `await` on async dependencies in tests** — when testing with TestClient, async dependencies are handled automatically. But if you call the dependency directly in tests, you must await it.
- **Dependencies that don't yield exactly once** — a dependency with `yield` must yield exactly once. Multiple yields or no yield causes a RuntimeError. The pattern is: setup → yield → cleanup.
- **Dependency override scope** — `app.dependency_overrides` is global. If you override in one test and forget to clear, it affects all subsequent tests. Always clear overrides in teardown or use a context manager.
- **Sync dependencies doing I/O** — a sync dependency that makes a DB query or API call blocks the event loop. Use async dependencies for I/O-bound work. FastAPI runs sync dependencies in a thread pool, but this consumes thread pool slots.
- **Circular dependencies** — if A depends on B and B depends on A, FastAPI raises an error at startup. Break the cycle by extracting shared logic into a third dependency.
- **Dependency parameter naming conflicts** — if a dependency returns a value and the endpoint parameter has the same name as a dependency's parameter, there's no conflict (they're in different scopes). But if two dependencies have parameters with the same name and both are used in the same endpoint, FastAPI handles them correctly (each dependency gets its own parameters).
- **Using `Depends` in nested models** — `Depends` only works in endpoint function signatures and dependency functions. You can't use it inside Pydantic models. For model-level dependencies, use a dependency that constructs the model.
- **Overusing dependencies** — not everything needs to be a dependency. Simple utility functions that don't need injection or cleanup should be regular functions. Dependencies are for cross-cutting concerns (auth, DB, config) that need to be injected or have lifecycle management.

## Practice

> [!question]- Q1. Design a dependency structure for a FastAPI application with the following requirements: (1) JWT-based authentication, (2) role-based access control (admin, user, guest), (3) database session per request, (4) request logging with correlation ID, (5) rate limiting per user. Show the dependency chain and which endpoints use which dependencies.
**Answer:**
```python
# auth.py
oauth2 = OAuth2PasswordBearer(tokenUrl="/auth/login")

async def get_token(token: str = Depends(oauth2)):
    try:
        return verify_jwt(token)
    except JWTError:
        raise HTTPException(401, "Invalid token")

async def get_user(payload: dict = Depends(get_token)):
    return await db.get_user(payload["sub"])

async def get_active_user(user: User = Depends(get_user)):
    if not user.is_active:
        raise HTTPException(403, "Inactive account")
    return user

def get_role(required_role: str):
    def checker(user: User = Depends(get_active_user)):
        if user.role != required_role:
            raise HTTPException(403, "Insufficient role")
        return user
    return checker

# db.py
async def get_db():
    db = Session()
    try:
        yield db
    finally:
        await db.close()

# logging.py
async def get_correlation_id(request: Request):
    cid = request.headers.get("X-Correlation-ID") or str(uuid4())
    request.state.correlation_id = cid
    logger.bind(correlation_id=cid)
    return cid

# rate_limit.py
async def rate_limit(user: User = Depends(get_active_user)):
    if await redis.get(f"rate:{user.id}") > 100:
        raise HTTPException(429, "Rate limit exceeded")
    await redis.incr(f"rate:{user.id}")
    await redis.expire(f"rate:{user.id}", 60)

# Endpoints:
@app.get("/public/")
async def public():  # No auth
    return {"msg": "public"}

@app.get("/user/")
async def user_endpoint(user: User = Depends(get_active_user)):
    return {"user": user}  # Auth required, any active user

@app.get("/admin/")
async def admin_endpoint(user: User = Depends(get_role("admin"))):
    return {"msg": "admin"}  # Admin only
```
The dependency chain: token → user → role check. Each endpoint uses the appropriate level. DB session, correlation ID, and rate limiting can be added as middleware or endpoint-level dependencies depending on scope. The key design: each security layer is a separate dependency, composed hierarchically. Role checking uses a dependency factory (`get_role`) to parameterize the required role.

> [!question]- Q2. You have a dependency that caches a database connection. The connection should be created once per application lifetime, shared across all requests, and closed on shutdown. Implement this with FastAPI dependencies and lifespan events.
**Answer:**
```python
from contextlib import asynccontextmanager
from fast import FastAPI

_db_pool = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _db_pool
    _db_pool = await create_connection_pool()  # Startup
    yield
    await _db_pool.close()  # Shutdown

app = FastAPI(lifespan=lifespan)

async def get_db():
    """Get a connection from the pool for this request"""
    conn = await _db_pool.acquire()
    try:
        yield conn
    finally:
        await _db_pool.release(conn)  # Return to pool, not close

# The pool is created once at startup (lifespan), stored in a module-level
# variable, and shared across all requests. Each request gets a connection
# from the pool via the get_db dependency, and returns it on completion.
# On shutdown, the pool is closed.

# Alternative: use a class-based dependency with app-level state:
class DatabasePool:
    def __init__(self):
        self.pool = None
    
    async def connect(self):
        self.pool = await create_connection_pool()
    
    async def disconnect(self):
        await self.pool.close()
    
    async def get_connection(self):
        return await self.pool.acquire()

db_pool = DatabasePool()

@asynccontextmanager
async def lifespan(app: FastAPI):
    await db_pool.connect()
    yield
    await db_pool.disconnect()

async def get_db():
    return await db_pool.get_connection()

app = FastAPI(lifespan=lifespan)
```
The key: the connection pool is created once at application startup (lifespan event), not per request. The `get_db` dependency acquires a connection from the pool for each request and releases it back. This is the standard pattern for database connection pooling — the pool is shared, connections are borrowed and returned. The lifespan event ensures proper startup and shutdown ordering.

> [!question]- Q3. Explain the difference between `Depends()`, `Security()`, and direct parameter injection (no Depends). When would you use each?
**Answer:** `Depends()` is the general dependency injection mechanism — it calls a function (sync or async) and injects the return value. Use for any reusable component: DB sessions, auth checks, config, pagination. `Security()` is like `Depends()` but integrates with OpenAPI security schemes — it shows the auth requirement in the API docs (lock icon, auth button). Use for authentication and authorization dependencies that should appear in the documentation. Direct parameter injection (no Depends) is for simple query/path/header/cookie/body parameters that FastAPI infers from type hints and defaults — e.g., `limit: int = 10` (query param), `item_id: int` (path param). Use for simple parameter extraction that doesn't need a custom function. The rule: if it needs custom logic or reuse → `Depends()`. If it's auth and should show in docs → `Security()`. If it's a simple parameter → direct injection. `Security()` is a thin wrapper over `Depends()` — it accepts the same arguments plus security scheme metadata.

> [!question]- Q4. A dependency with `yield` raises an exception in its cleanup code (after yield). What happens to the endpoint's response? Explain the error handling flow.
**Answer:** The flow: endpoint runs → endpoint returns response (or raises) → dependency cleanup runs (code after yield) → if cleanup raises, the exception propagates. If the endpoint already returned a response successfully, the cleanup exception replaces the response — the client gets a 500 instead of the successful response. If the endpoint raised an exception, the cleanup exception may mask the original exception (depending on Python's exception chaining). This is why cleanup code in dependencies should be defensive — wrap it in try/except and log errors instead of raising. The pattern:
```python
async def get_db():
    db = connect()
    try:
        yield db
    except Exception as e:
        # Endpoint raised — log it
        logger.error(f"Endpoint error: {e}")
        raise  # Re-raise so the endpoint error is preserved
    finally:
        try:
            db.close()  # Cleanup in finally — exceptions here are logged
        except Exception as e:
            logger.error(f"DB close error: {e}")
            # Don't raise — don't mask the original error
```
The key principle: cleanup code should never raise an exception that masks the original response or error. Use `finally` for cleanup and catch exceptions there. If you need to propagate cleanup errors, use a separate mechanism (e.g., store them in request state and handle in middleware).

> [!question]- Q5. You want to apply a dependency to ALL routes in the application (e.g., global auth, global CORS preflight handling). What are the options, and what are the trade-offs of each?
**Answer:** Option 1: `app = FastAPI(dependencies=[Depends(global_dep)])` — applies to all routes. Simple but applies to EVERY route, including health checks and static files that might not need it. Option 2: `APIRouter(dependencies=[...])` and include all routes through the router — applies to all routes in the router. More flexible — you can have multiple routers with different global deps. Option 3: Middleware — applies to every request at the ASGI level, before routing. Good for cross-cutting concerns that apply to all requests (CORS, logging, request timing) but NOT for dependencies that need to inject values into endpoints. Option 4: Mix — middleware for truly global concerns (CORS, logging), router dependencies for route-group concerns (auth for API routes), endpoint dependencies for specific concerns. The recommended approach: middleware for CORS, logging, timing; router dependencies for auth (on API routers); no global `FastAPI(dependencies=...)` unless you genuinely need every single route to have the dependency. The trade-off: global dependencies are simple but inflexible. Router dependencies are modular. Middleware is lowest-level but can't inject values into endpoints. Use each at the appropriate layer.

## Related
[[request-response-lifecycle]]
[[middleware]]
[[auth-oauth2-jwt]]
[[database-integration-async-orm]]
[[testing-fastapi]]

#status/new