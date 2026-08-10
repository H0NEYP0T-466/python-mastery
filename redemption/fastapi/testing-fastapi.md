# Testing FastAPI

## What it is
Testing a FastAPI API means verifying that endpoints behave correctly under various conditions — valid input, invalid input, auth failures, database errors, edge cases. FastAPI's `TestClient` (built on Starlette's test client, which wraps httpx) lets you make HTTP requests to your app without starting a server. This file covers the testing pyramid (unit, integration, E2E), dependency overrides for mocking, async testing, database testing in isolation, property-based testing, and the patterns that make FastAPI tests fast, reliable, and maintainable.

## Why it matters
Without tests, every change is a gamble. A working API today can break tomorrow from a seemingly unrelated change. In interviews, testing questions test whether you understand the testing pyramid, how to mock dependencies, and the difference between unit and integration tests. For your work — building APIs that serve real users and ML models — tests are your safety net. The faster your tests run and the more they cover, the more confidently you can ship changes.

## Core example

### The testing pyramid for FastAPI

```
         E2E tests (10%)
        /   Full stack, slow, fragile
       /
  Integration tests (20%)
  /   DB + API, medium speed
 /
Unit tests (70%)
— Fast, isolated, focused
```

- **Unit tests** (70%): Test individual functions, Pydantic models, CRUD operations, service logic. No DB, no network. Fast (ms per test). Use dependency overrides to mock external dependencies.
- **Integration tests** (20%): Test the full API layer with a real test database. No external services (use TestContainer or mocks). Medium speed (10-100ms per test). Test actual HTTP responses, DB persistence, auth flow.
- **E2E tests** (10%): Test the full stack — API + DB + external services + frontend. Slow (seconds per test). Fragile (depends on external systems). Use sparingly for critical user journeys.

### Basic TestClient usage

```python
from fastapi.testclient import TestClient
from myapp.main import app

client = TestClient(app)

# Simple GET request
def test_read_root():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "hello"}

# POST request with JSON body
def test_create_item():
    response = client.post(
        "/items/",
        json={"name": "Laptop", "price": 999.99},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Laptop"
    assert data["id"] is not None

# Query parameters
def test_list_items():
    response = client.get("/items/?skip=0&limit=10")
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) <= 10

# Path parameters
def test_get_item():
    response = client.get("/items/1")
    assert response.status_code == 200
    assert response.json()["id"] == 1

# Headers
def test_with_header():
    response = client.get("/protected/", headers={"X-API-Key": "secret"})
    assert response.status_code == 200

# Response validation
def test_response_structure():
    response = client.get("/items/1")
    data = response.json()
    # Validate against Pydantic model
    assert Item.model_validate(data)  # Raises if invalid
```

### Dependency overrides — the key to isolated testing

```python
# In production, get_current_user verifies JWT and queries the DB.
# In tests, we want to skip all that and inject a test user.

from myapp import dependencies
from myapp.models import User

test_user = User(id=1, username="testuser", role="user")

def override_get_current_user():
    return test_user

def override_get_db():
    # Use a test database session
    return test_db_session

# Apply overrides before creating TestClient
app.dependency_overrides[dependencies.get_current_user] = override_get_current_user
app.dependency_overrides[dependencies.get_db] = override_get_db

client = TestClient(app)

# Now, any endpoint that uses get_current_user gets test_user
# without needing a valid JWT or DB lookup.

# Test auth-protected endpoint without auth:
def test_protected_endpoint():
    response = client.get("/users/me")
    assert response.status_code == 200
    assert response.json()["username"] == "testuser"
    # No JWT needed — dependency override bypasses auth

# Clean up after tests:
def teardown():
    app.dependency_overrides.clear()

# Or use a fixture (pytest):
@pytest.fixture
def auth_client():
    app.dependency_overrides[dependencies.get_current_user] = override_get_current_user
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()

def test_protected(auth_client):
    response = auth_client.get("/users/me")
    assert response.status_code == 200
```

### Testing database interactions — isolation and cleanup

```python
# Each test should have a clean database state.
# Options: transaction rollback, database truncation, fresh DB per test.

# Option 1: Transaction rollback (fastest, recommended for SQLAlchemy)
# Wrap each test in a transaction. Rollback at the end.
# No data persists between tests.

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for async tests"""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()

@pytest.fixture
async def db_session():
    """Create a fresh DB session for each test with rollback"""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    
    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession)
    
    async with AsyncSessionLocal() as session:
        yield session
        
        # Rollback after test
        await session.rollback()
    
    # Drop tables after all tests
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()

# In test:
async def test_create_user(db_session):
    user = await create_user(db_session, UserCreate(name="Alice"))
    assert user.name == "Alice"
    
    # Verify in DB
    retrieved = await get_user(db_session, user.id)
    assert retrieved is not None
    # No need to clean up — transaction rollback handles it

# Option 2: Database truncation (works with any DB)
# Truncate all tables after each test.

@pytest.fixture
async def db_session():
    session = AsyncSessionLocal()
    yield session
    await session.close()
    
    # Truncate all tables
    async with engine.begin() as conn:
        await conn.run_sync(truncate_all_tables)

def truncate_all_tables(metadata):
    """Truncate all tables, reset sequences"""
    for table in reversed(metadata.sorted_tables):
        print(f"Truncating {table.name}")
        # Use TRUNCATE with CASCADE for PostgreSQL
```

### Testing async endpoints and dependencies

```python
# FastAPI TestClient handles async endpoints automatically.
# You don't need to await the client methods.

# But async dependencies and async test functions need care.

# Test function can be async (pytest-asyncio):
import pytest
from pytest import mark

@pytest.mark.asyncio
async def test_async_endpoint():
    response = client.get("/async-endpoint/")
    assert response.status_code == 200

# Or use the sync TestClient for async endpoints:
def test_async_endpoint_sync():
    response = client.get("/async-endpoint/")
    assert response.status_code == 200
    # TestClient handles the event loop internally

# For testing async functions directly (not through the API):
@pytest.mark.asyncio
async def test_async_function():
    result = await some_async_function(arg1, arg2)
    assert result == expected

# Configure pytest-asyncio in pytest.ini:
# [pytest]
# asyncio_mode = auto
# This auto-detects async test functions and runs them properly.

# Testing WebSocket endpoints:
def test_websocket():
    with client.websocket_connect("/ws/") as websocket:
        websocket.send_json({"message": "hello"})
        data = websocket.receive_json()
        assert data["response"] == "hello"
```

### Testing error responses

```python
# Test that your API returns correct error responses for various
# error conditions. This ensures consistent error handling.

def test_404_not_found():
    response = client.get("/items/99999")  # Non-existent ID
    assert response.status_code == 404
    data = response.json()
    assert data["error"] == "not_found"
    assert "detail" in data

def test_422_validation_error():
    response = client.post("/items/", json={"name": None})  # Invalid
    assert response.status_code == 422
    data = response.json()
    assert data["error"] == "validation"
    # Check specific field errors
    field_errors = data.get("errors", [])
    assert any(e["field"] == "name" for e in field_errors)

def test_401_unauthorized():
    # Without auth header
    response = client.get("/protected/")
    assert response.status_code == 401

def test_403_forbidden():
    # With valid auth but insufficient role
    # Override with a non-admin user
    app.dependency_overrides[get_current_user] = lambda: User(role="user")
    response = client.get("/admin/")
    assert response.status_code == 403

def test_400_bad_request():
    response = client.post("/items/", json={})  # Missing required fields
    assert response.status_code == 400

def test_409_conflict():
    response = client.post("/users/", json={"email": "existing@test.com"})
    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]

def test_429_rate_limited():
    # Make many requests
    for _ in range(101):
        client.get("/rate-limited/")
    response = client.get("/rate-limited/")
    assert response.status_code == 429
    assert "Retry-After" in response.headers
```

### Testing middleware

```python
# Middleware is tested through the TestClient — make requests and
# check the response headers/status.

def test_cors_headers():
    # Make a request with Origin header (simulating browser)
    response = client.get(
        "/",
        headers={"Origin": "https://myapp.com"},
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://myapp.com"
    assert response.headers["access-control-allow-credentials"] == "true"

def test_request_id_header():
    response = client.get("/")
    assert response.status_code == 200
    assert "x-request-id" in response.headers
    # Verify it's a valid UUID
    uuid.UUID(response.headers["x-request-id"])

def test_timing_header():
    response = client.get("/")
    assert response.status_code == 200
    assert "x-response-time" in response.headers
    # Should be a number with "ms" suffix
    assert response.headers["x-response-time"].endswith("ms")

def test_maintenance_mode():
    # Enable maintenance mode (set global flag)
    set_maintenance_mode(True)
    try:
        response = client.get("/")
        assert response.status_code == 503
        assert "maintenance" in response.json()["error"]
    finally:
        set_maintenance_mode(False)

def test_middleware_short_circuit():
    # Test that auth middleware rejects unauthenticated requests
    response = client.get("/protected/")
    assert response.status_code == 401
    # The endpoint should NOT be called — verify no DB queries
    # (this is tested via dependency override + mock)
```

### Property-based testing with hypothesis

```python
# Property-based testing: instead of writing specific test cases,
# you define properties that should always hold, and a testing
# library generates hundreds of inputs to try to break them.

from hypothesis import given, strategies as st

# Test that user creation always returns a valid user
@given(
    name=st.text(min_size=1, max_length=100),
    email=st.emails(),
    age=st.integers(min_value=0, max_value=120),
)
def test_create_user_valid(name, email, age):
    response = client.post(
        "/users/",
        json={"name": name, "email": email, "age": age},
    )
    # Property: if input is valid, response should be 201 with valid data
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == name
    assert data["email"] == email
    assert "id" in data

# Test that invalid input always returns 422
@given(
    name=st.text(max_length=0),  # Empty name
    email=st.text(),  # Any string (may not be valid email)
)
def test_create_user_invalid(name, email):
    response = client.post(
        "/users/",
        json={"name": name, "email": email},
    )
    # Property: if input is invalid, response should be 422
    # (at least one of name or email should fail validation)
    assert response.status_code in [422, 400]

# The advantage: hypothesis finds edge cases you wouldn't think of.
# Empty strings, Unicode, very long strings, special characters.
# It shrinks failures to the minimal reproducing case.
# Install: pip install hypothesis
```

### Test organization and fixtures

```python
# tests/conftest.py — shared fixtures for all tests
import pytest
from fastapi.testclient import TestClient
from myapp.main import app
from myapp import dependencies
from myapp.database import engine, get_db
from myapp.models import Base

# Override DB dependency with test DB
@pytest.fixture(scope="session")
def setup_test_db():
    """Create test database schema once per session"""
    Base.metadata.create_all(bind=engine.sync_engine)
    yield
    Base.metadata.drop_all(bind=engine.sync_engine)

@pytest.fixture
def db_session(setup_test_db):
    """Fresh DB session per test with rollback"""
    with SessionLocal() as session:
        yield session
        session.rollback()  # Rollback after each test

@pytest.fixture
def auth_client(db_session):
    """Test client with authenticated user"""
    test_user = User(id=1, username="testuser", role="user")
    
    def override_get_db():
        return db_session
    
    def override_get_current_user():
        return test_user
    
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[dependencies.get_current_user] = override_get_current_user
    
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()

@pytest.fixture
def admin_client(db_session):
    """Test client with admin user"""
    test_admin = User(id=2, username="admin", role="admin")
    
    def override_get_current_user():
        return test_admin
    
    app.dependency_overrides[dependencies.get_current_user] = override_get_current_user
    
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()

# tests/test_users.py
def test_create_user(auth_client):
    response = auth_client.post(
        "/users/",
        json={"name": "Alice", "email": "alice@test.com"},
    )
    assert response.status_code == 201

def test_get_user(auth_client, db_session):
    # Create user in DB first
    user = create_user(db_session, UserCreate(name="Bob", email="bob@test.com"))
    
    response = auth_client.get(f"/users/{user.id}")
    assert response.status_code == 200
    assert response.json()["name"] == "Bob"

def test_admin_only(admin_client, auth_client):
    # Regular user can't access admin endpoint
    response = auth_client.get("/admin/")
    assert response.status_code == 403
    
    # Admin can
    response = admin_client.get("/admin/")
    assert response.status_code == 200
```

## Common mistakes / gotchas

- **Not isolating test databases** — tests that share a database state flake. One test's data affects another's. Always use transaction rollback or database truncation between tests.
- **Testing through HTTP when unit testing is enough** — `client.post("/items/")` tests the full stack. If you just want to test a function, call it directly. Integration tests are slower and more fragile.
- **Forgetting to clear dependency overrides** — overrides persist across tests if not cleared. Use fixtures with proper teardown or `app.dependency_overrides.clear()` in teardown.
- **Testing implementation details** — testing that a specific function was called or a specific SQL query was executed. Test the behavior (response), not the implementation.
- **Async test functions without pytest-asyncio** — async test functions need pytest-asyncio to run properly. Without it, the test passes but the async code never executes.
- **Not testing error paths** — only testing the happy path. Test 400, 401, 403, 404, 409, 422, 429, 500 responses. These are often where bugs hide.
- **Slow tests from not mocking external services** — if your test calls a real external API or sends real emails, it's slow and flaky. Mock external services with responses or dependency overrides.
- **Too many E2E tests** — E2E tests are slow and brittle. Keep them to critical user journeys only. Most coverage should come from unit and integration tests.

## Practice

> [!question]- Q1. Design a test suite for a FastAPI ML inference API with the following endpoints: POST /predict/ (single), POST /predict/batch/ (batch), GET /models/ (list models), GET /health/ (health check). Include unit, integration, and E2E tests with specific test cases for each.
**Answer:** 
- **Unit tests (70%)**: Pydantic model validation (valid/invalid input schemas), preprocessing functions (image normalization, tokenization), postprocessing (logits → labels), model registry (version selection, fallback logic), cache key generation (deterministic, includes all params), rate limiting algorithm (sliding window counter correctness).
- **Integration tests (20%)**: POST /predict/ with valid input → 200 with correct output shape, POST /predict/ with invalid input → 422 with field errors, POST /predict/batch/ → 200 with array of results, GET /models/ → 200 with model list and versions, GET /health/ → 200 when all dependencies ok, 503 when model not loaded, auth tests (valid token → success, no token → 401, wrong role → 403), rate limiting test (101 requests → 429 on 102nd), cache test (same input twice → second is faster with X-Cache-Hit header), model version test (explicit version → correct model used).
- **E2E tests (10%)**: Full inference pipeline from image upload to prediction result, batch inference with 10 images, model switch (v1 → v2, predictions change), health check after model reload, concurrent requests (50 simultaneous → all succeed within latency SLO). The key: unit tests cover the ML logic (preprocessing, model selection), integration tests cover the API layer (auth, validation, error handling), E2E tests cover critical user journeys (complete inference pipeline).

> [!question]- Q2. You need to test a FastAPI endpoint that sends emails. The email service is external (SendGrid). How do you test this without sending real emails?
**Answer:** Three approaches: (1) **Dependency override** — replace the email service with a mock that records sent emails instead of sending them. In the test, assert that the mock was called with the correct parameters. (2) **Test email backend** — use Django's locmem email backend equivalent or a test SMTP server that captures emails. Assert on the captured emails. (3) **Integration test with test API key** — use SendGrid's test API key which doesn't actually send emails but returns success responses. Verify the API call was made. The recommended approach: dependency override with a mock. It's fast (no network), deterministic (no external service), and tests the integration point (was the email service called correctly). The mock records recipient, subject, body, and attachments. In the test: `assert mock_email_service.last_call.recipient == "user@test.com"` and `assert "welcome" in mock_email_service.last_call.subject`. For end-to-end verification: use SendGrid test key in a staging environment and verify the email is queued (not sent). Never test with real emails in production.

> [!question]- Q3. A FastAPI endpoint uses a dependency that calls an external API. The external API is sometimes slow (5s response) and sometimes returns 503. Design tests that cover these scenarios without depending on the real external API.
**Answer:** Use dependency override to replace the external API client with a mock that can simulate different behaviors:
```python
class MockExternalAPI:
    def __init__(self):
        self.response = {"data": "mocked"}
        self.status_code = 200
        self.latency = 0.1
        self.call_count = 0
    
    async def fetch(self, *args, **kwargs):
        self.call_count += 1
        await asyncio.sleep(self.latency)
        if self.status_code >= 400:
            raise ExternalAPIError(self.status_code, "External service error")
        return self.response

# Test normal case:
def test_endpoint_normal():
    mock = MockExternalAPI()
    app.dependency_overrides[ExternalAPIClient] = lambda: mock
    response = client.get("/endpoint/")
    assert response.status_code == 200
    assert mock.call_count == 1

# Test slow external API:
def test_endpoint_slow():
    mock = MockExternalAPI()
    mock.latency = 5.0  # 5 second delay
    app.dependency_overrides[ExternalAPIClient] = lambda: mock
    # Test that the endpoint handles slow responses gracefully
    # (e.g., returns a cached response or times out)
    response = client.get("/endpoint/", timeout=10)
    # Assert based on your timeout/caching strategy

# Test external API 503:
def test_endpoint_external_error():
    mock = MockExternalAPI()
    mock.status_code = 503
    app.dependency_overrides[ExternalAPIClient] = lambda: mock
    response = client.get("/endpoint/")
    # Assert your error handling — fallback, cached data, or 502
    assert response.status_code in [200, 502, 503]

# Test rate limiting on external API:
def test_external_rate_limit():
    mock = MockExternalAPI()
    mock.status_code = 429
    app.dependency_overrides[ExternalAPIClient] = lambda: mock
    response = client.get("/endpoint/")
    assert response.status_code == 429  # Or retry with backoff
```
The key: the mock can simulate any behavior (latency, errors, rate limits) without depending on the real external API. Tests are fast, deterministic, and cover edge cases that are hard to reproduce with the real service.

> [!question]- Q4. Your FastAPI test suite has grown to 500 tests and takes 8 minutes to run. Developers are skipping tests before committing. Diagnose the slowness and propose a plan to get it under 2 minutes.
**Answer:** Diagnosis: run tests with `--durations=10` to find the 10 slowest tests. Profile with `pytest --profile` to see where time is spent. Common causes and fixes: (1) **Database setup/teardown per test** — creating/dropping tables for each test is slow. Fix: create tables once per test session, use transaction rollback per test. Saves 5-10s per test. (2) **Real external service calls** — tests that call real APIs, send real emails, or use real ML models. Fix: mock all external services. Replace ML model calls with mock predictions. Saves seconds per test. (3) **Too many integration tests** — 500 tests with 80% integration is too many. Fix: rebalance — 70% unit (fast, <1ms), 20% integration (10-100ms), 10% E2E (1-5s). Convert integration tests to unit tests where possible. (4) **No parallelization** — running tests sequentially. Fix: use `pytest-xdist` to run tests in parallel (`pytest -n auto`). With 4 cores, 4x speedup. (5) **Shared state between tests** — tests that depend on each other's data can't run in parallel. Fix: ensure test isolation (transaction rollback). (6) **Unnecessary test data** — creating 100 test records when 2 suffice. Fix: use factories (Factory Boy) with minimal data. Plan: Phase 1 — Mock external services (saves 2-3 min). Phase 2 — Fix database setup (session-level create, per-test rollback) (saves 1-2 min). Phase 3 — Parallelize with pytest-xdist (saves 2-3 min with 4 cores). Phase 4 — Rebalance test pyramid (convert 30% integration to unit) (saves 1-2 min). Target: under 2 minutes.

> [!question]- Q5. Explain the difference between mocking, stubbing, and faking in testing. Give an example of each in the context of testing a FastAPI endpoint that depends on a database and an external payment gateway.
**Answer:** Mocking: replacing a dependency with a fake that records how it was called (what methods, with what arguments). You assert on the interactions. Example: mock the payment gateway — `mock_payment.charge.assert_called_once_with(user_id=1, amount=99.99)`. Use when you want to verify that your code called the dependency correctly. Stubbing: replacing a dependency with a fake that returns predetermined responses. You don't assert on interactions, just on the result. Example: stub the database — `stub_db.get_user.return_value = User(id=1, name="Alice")`. The endpoint uses this stubbed user. Use when you need the dependency to return specific data but don't care how it's called. Faking: replacing a dependency with a working implementation that's simpler/faster than the real thing. Example: fake the database with an in-memory dict — `class FakeDB: def __init__(self): self.users = {}; def get(self, id): return self.users.get(id)`. It's a real database implementation, just in-memory. Use when you need realistic behavior without the overhead of the real dependency. For FastAPI testing: mock the payment gateway (verify the charge was called with correct amount). Stub the database for specific test cases (user not found, invalid user). Fake the database for integration tests (in-memory SQLite or dict-based). The distinction matters because each serves a different testing purpose — mocks verify behavior, stubs provide data, fakes provide realistic behavior.

## Related
[[dependency-injection]]
[[error-handling-and-exception-handlers]]
[[database-integration-async-orm]]
[[env-and-config-management]]
[[logging-and-monitoring]]

#status/new