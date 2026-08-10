# Testing with pytest

## What it is
pytest is the dominant testing framework in Python — it's more expressive than unittest (no boilerplate class definitions), supports fixtures for setup/teardown, parametrization for running the same test with multiple inputs, and a rich plugin ecosystem. But pytest's real power comes from its philosophy: tests are plain Python functions with `assert` statements (no `self.assertEqual`), fixtures compose hierarchically, and the test discovery is automatic. This file covers the mechanics — fixtures, parametrization, conftest, mocking, property-based testing — and the patterns that separate maintainable test suites from brittle ones.

## Why it matters
Testing is often the first thing skipped when you're building things fast (you've done this — GPT-2 training during exams week, DINOv2 SOTA, all pushed without a test suite). But in production, tests are your safety net. In interviews, testing questions test whether you understand fixture scoping, mocking strategies, and the difference between unit, integration, and end-to-end tests. More practically: a well-structured pytest suite lets you refactor with confidence, catch regressions before they hit production, and document expected behavior through examples. For your FastAPI work, testing is non-negotiable — FastAPI's TestClient makes testing endpoints trivial, and there's no excuse not to.

## Core example

### The simplest pytest test — no classes, no boilerplate

```python
# test_math.py
def test_add():
    assert 1 + 1 == 2

def test_divide():
    assert 10 / 2 == 5

# That's it. No class TestMath, no self.assertEqual, no setUp/tearDown.
# pytest discovers any function named test_* and runs it.
# assert is just Python's assert — no special assertion methods needed.

# Run: $ pytest test_math.py -v
# Or: $ pytest -v (discovers all test_*.py files)

# If an assertion fails, pytest shows the actual values:
def test_add():
    assert 1 + 1 == 3  # Fails with: assert 2 == 3
                       # Where 2 is the value of (1 + 1)
# pytest rewrites the AST to show intermediate values — this is the
# "assertion rewriting" feature that makes pytest's failure messages
# far more useful than unittest's.
```

### Fixtures — the heart of pytest

```python
# Fixtures are functions that set up state for tests. They're declared
# with @pytest.fixture and injected into tests by name.

import pytest

@pytest.fixture
def db_connection():
    """Set up a database connection — runs before each test"""
    conn = connect_to_test_db()  # Create a fresh test DB
    yield conn  # Yield to the test
    conn.close()  # Teardown — runs after the test, even if it fails

def test_user_create(db_connection):
    # db_connection is injected automatically
    user = db_connection.create_user("Alice")
    assert user.name == "Alice"

def test_user_delete(db_connection):
    # Each test gets a FRESH db_connection — fixtures are isolated
    user = db_connection.create_user("Bob")
    db_connection.delete_user(user.id)
    assert db_connection.get_user(user.id) is None

# Fixture scopes — control how often the fixture is set up:
# - function (default): run before each test function
# - class: run once per test class
# - module: run once per test module
# - session: run once per test session (across all files)

@pytest.fixture(scope="session")
def expensive_resource():
    """Set up once for the entire test session — useful for slow setup"""
    resource = load_heavy_model()  # Takes 30 seconds
    yield resource
    # Cleanup runs once at the end of all tests

# The yield pattern is key: code before yield is setup, code after yield
# is teardown. The teardown runs even if the test fails — it's like a
# finally block. If you don't need teardown, just return instead of yield.

# Fixtures can use other fixtures — they compose:
@pytest.fixture
def db_with_data(db_connection):
    db_connection.create_user("Alice")
    db_connection.create_user("Bob")
    return db_connection  # Now tests get a pre-populated DB

def test_list_users(db_with_data):
    users = db_with_data.list_users()
    assert len(users) == 2  # Alice and Bob are already there
```

### `conftest.py` — shared fixtures across test files

```python
# conftest.py is a pytest configuration file that's automatically
# loaded. Fixtures defined here are available to all test files in
# the directory tree — no import needed.

# conftest.py (at project root):
import pytest

@pytest.fixture
def api_client():
    """Shared API client fixture — available to all tests"""
    return TestClient(app)

# tests/test_users.py:
def test_create_user(api_client):  # Fixture from conftest.py injected
    response = api_client.post("/users", json={"name": "Alice"})
    assert response.status_code == 201

# tests/test_posts.py:
def test_create_post(api_client):  # Same fixture — no import needed
    response = api_client.post("/posts", json={"title": "Hello"})
    assert response.status_code == 201

# You can have multiple conftest.py files at different directory levels.
# pytest loads them from the root down, and fixtures in deeper conftest.py
# override fixtures with the same name in parent conftest.py.
# This is useful for project-wide fixtures (root conftest.py) plus
# module-specific overrides (subdirectory conftest.py).
```

### Parametrization — one test, many inputs

```python
import pytest

# Instead of writing multiple test functions for different inputs,
# use @pytest.mark.parametrize to run one test with multiple cases.

@pytest.mark.parametrize("input,expected", [
    (2, 4),
    (3, 9),
    (4, 16),
    (-1, 1),
    (0, 0),
])
def test_square(input, expected):
    assert square(input) == expected

# This runs 5 separate test cases. If one fails, the others still run.
# pytest reports each parametrized case separately:
# test_square[2-4] PASSED
# test_square[3-9] PASSED
# test_square[-1-1] PASSED
# ...

# Parametrize with IDs for readable names:
@pytest.mark.parametrize("input,expected", [
    (2, 4),
    (3, 9),
    (0, 0),
], ids=["positive", "positive", "zero"])
def test_square(input, expected):
    ...
# Reports: test_square[positive], test_square[zero] — more readable.

# Parametrize with fixtures — you can pass fixture names to parametrize:
@pytest.fixture
def db():
    return connect()

@pytest.mark.parametrize("role", ["admin", "user", "guest"])
def test_permissions(db, role):  # db fixture + parametrized role
    # Runs 3 times, each with a fresh db connection and different role
    ...

# Parametrize over multiple arguments:
@pytest.mark.parametrize("a,b,expected", [
    (1, 2, 3),
    (2, 3, 5),
    (0, 0, 0),
])
def test_add(a, b, expected):
    assert add(a, b) == expected
```

### Mocking — replacing dependencies in tests

```python
from unittest.mock import patch, MagicMock

# When your code depends on external services (APIs, databases, file system),
# you mock them to make tests fast, deterministic, and isolated.

# Patch decorator — replaces a function/method with a mock:
@patch("myapp.requests.get")
def test_fetch_user(mock_get):
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {"id": 1, "name": "Alice"}
    
    result = fetch_user(1)
    
    mock_get.assert_called_once_with("https://api.example.com/users/1")
    assert result.name == "Alice"
    assert result.id == 1

# Patch as a context manager — for patching in specific code blocks:
def test_fetch_user_with_context():
    with patch("myapp.requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        result = fetch_user(1)
        assert result.name == "Alice"
    # Patch is automatically undone after the context

# MagicMock — an object that records all interactions:
mock = MagicMock()
mock.method(1, 2, key="value")
mock.method.assert_called_once_with(1, 2, key="value")
mock.method.assert_called()  # Was called at least once
mock.other_method.assert_not_called()

# Side effects — make a mock raise an exception or return different values:
mock.side_effect = [ValueError("first call"), "second call result"]
mock()  # Raises ValueError
mock()  # Returns "second call result"

mock.side_effect = Exception("boom")
mock()  # Raises Exception

# When to mock:
# - External HTTP APIs (requests, aiohttp)
# - Database calls (if testing business logic, not DB integration)
# - File system operations (if testing logic, not file I/O)
# - Time-dependent code (use freeze_time or patch time.time)

# When NOT to mock:
# - When testing the integration itself (use a real test DB, real API)
# - When the mock is more complex than the real thing
# - When you're testing a third-party library (use it directly)
```

### Property-based testing — testing properties, not examples

```python
# Traditional testing: you write specific examples (test_add(1, 2, 3)).
# Property-based testing: you define a property that should hold for ALL
# inputs, and the framework generates random inputs to try to break it.

# Using hypothesis (pip install hypothesis):
from hypothesis import given, strategies as st

# Property: reversing a list twice gives the original list
@given(st.lists(st.integers()))
def test_reverse_twice(lst):
    assert lst[::-1][::-1] == lst

# Property: sorting a list makes it sorted
@given(st.lists(st.integers()))
def test_sort_is_sorted(lst):
    sorted_lst = sorted(lst)
    assert sorted_lst == sorted(sorted_lst)  # Idempotent
    assert all(sorted_lst[i] <= sorted_lst[i+1] for i in range(len(sorted_lst)-1))

# Hypothesis generates hundreds of random inputs and tries to find
# counterexamples. If it finds one, it shrinks the input to the minimal
# failing case and reports it. This catches edge cases you'd never think to test.

# For your ML work: property-based testing is useful for data validation.
# Property: all images in the dataset have the same number of channels.
# Property: all labels are within the valid range.
# Property: data augmentation preserves the label while transforming the image.
# These properties, when tested with generated inputs, catch bugs that
# example-based testing would miss.

# The trade-off: property-based tests are slower (hundreds of inputs)
# and require thinking in terms of invariants rather than examples.
# Use them for core algorithms and data invariants, not for every function.
```

### Test organization — layout and structure

```python
# Recommended project layout:
myproject/
├── src/
│   └── mypackage/
│       ├── __init__.py
│       ├── module1.py
│       └── module2.py
├── tests/
│   ├── __init__.py  # Optional — makes tests a package
│   ├── conftest.py  # Shared fixtures
│   ├── test_module1.py
│   ├── test_module2.py
│   └── integration/
│       ├── test_api.py
│       └── test_database.py
├── pyproject.toml
└── README.md

# Test naming conventions:
# - Test files: test_*.py or *_test.py (pytest discovers both)
# - Test functions: test_*
# - Test classes: Test* (no __init__ — use fixtures instead)

# Unit vs integration vs end-to-end:
# - Unit tests: test individual functions/classes in isolation (mock deps)
#   Fast, deterministic, many of them. Run on every commit.
# - Integration tests: test interactions between components (real DB, real API)
#   Slower, fewer of them. Run on PRs or nightly.
# - End-to-end tests: test the full system from the outside (browser, API)
#   Slowest, fewest of them. Run on release candidates.

# The testing pyramid: many unit tests, fewer integration tests, few E2E tests.
# Don't invert the pyramid — it leads to slow, flaky test suites.
```

### pytest plugins — extending the framework

```python
# pytest-cov — code coverage
# $ pytest --cov=mypackage --cov-report=term-missing

# pytest-mock — simpler mocking (mocker fixture instead of patch)
# def test_something(mocker):
#     mocker.patch("module.function")
#     # Automatically undoes patch after test

# pytest-asyncio — test async functions
# @pytest.mark.asyncio
# async def test_async():
#     result = await async_function()
#     assert result == expected

# pytest-freezegun — freeze time for testing
# @pytest.mark.freeze_time("2024-01-01 12:00:00")
# def test_time_dependent():
#     assert datetime.now() == datetime(2024, 1, 1, 12, 0, 0)

# pytest-xdist — parallel test execution
# $ pytest -n auto  # Runs tests in parallel across all CPU cores
# 2-5x speedup for large test suites

# For your FastAPI work: pytest-asyncio is essential for testing async endpoints.
# pytest-cov ensures you're not shipping untested code. pytest-xdist speeds
# up CI runs. These are the core plugins you should install by default.
```

## Common mistakes / gotchas

- **Test order dependence** — tests should be independent. If test B depends on test A's state (e.g., data left in a DB), your tests are flaky. Use fresh fixtures for each test, and never assume test execution order.
- **Over-mocking** — mocking everything makes tests brittle (they break when implementation changes) and meaningless (you're testing mocks, not code). Mock only external dependencies, not the code under test.
- **Testing implementation details** — test behavior, not implementation. If you test `obj._internal_counter` instead of `obj.get_count()`, refactoring breaks the test even when behavior is correct. Test the public API.
- **Slow tests** — if your test suite takes >5 minutes to run, developers won't run it locally. Use fixtures with appropriate scope, mock slow dependencies, and parallelize with pytest-xdist. Separate slow integration tests from fast unit tests.
- **Not cleaning up after tests** — test databases, temporary files, network connections. Use fixture teardown (the `yield` pattern) to ensure cleanup. Leaked resources cause flaky tests.
- **`scope="session"` fixtures with mutable state** — a session-scoped fixture is shared across all tests. If one test mutates the state, other tests see the mutation. Either make session fixtures immutable, or use function/class scope for mutable state.
- **Assertion errors without context** — `assert result` is less informative than `assert result, f"Expected user to be created, got {result}"`. pytest shows the assertion expression, but a custom message helps when the expression is complex.
- **Testing private methods** — test through the public API. If you need to test a private method directly, it's probably a sign that the method should be public or extracted. Private methods are implementation details — testing them couples tests to implementation.

## Practice

> [!question]- Q1. You have a function `send_notification(user_id, message)` that sends an email via an external API. Write a test that verifies the correct API call is made without actually sending an email. Use mocking.
**Answer:**
```python
from unittest.mock import patch

@patch("myapp.requests.post")
def test_send_notification(mock_post):
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {"status": "sent"}
    
    result = send_notification(42, "Hello!")
    
    # Verify the API was called correctly
    mock_post.assert_called_once_with(
        "https://api.emailservice.com/send",
        json={
            "to": "user42@example.com",  # Assuming user lookup happens
            "message": "Hello!",
        },
        headers={"Authorization": "Bearer ..."},
    )
    
    # Verify the result
    assert result == {"status": "sent"}
    
    # Verify no actual HTTP call was made
    mock_post.assert_called()  # Called the mock, not the real API
```
The test patches `requests.post` at the point of use in the module. The mock returns a fake response, so no real HTTP call is made. The test verifies the correct URL, payload, and headers were used. The key is patching at the right location — where the function imports and uses the dependency, not where it's defined. If `myapp` does `import requests` and then `requests.post()`, you patch `"myapp.requests.post"`. If it does `from requests import post` and then `post()`, you patch `"myapp.post"`.

> [!question]- Q2. Write a parametrized test for a function `is_palindrome(s)` that handles edge cases. Include at least 8 test cases covering normal, edge, and error cases.
**Answer:**
```python
import pytest

@pytest.mark.parametrize("s,expected", [
    # Normal cases
    ("racecar", True),
    ("hello", False),
    # Case insensitivity
    ("RaceCar", True),
    ("Madam", True),
    # With spaces and punctuation
    ("A man a plan a canal Panama", True),
    ("Was it a car or a cat I saw", True),
    # Edge cases
    ("", True),  # Empty string is a palindrome
    ("a", True),  # Single character
    ("ab", False),  # Two different characters
    # Numbers
    ("12321", True),
    ("12345", False),
    # Mixed
    ("No 'x' in Nixon", True),
])
def test_is_palindrome(s, expected):
    assert is_palindrome(s) == expected
```
The test covers: normal palindromes and non-palindromes, case insensitivity (a common bug), spaces and punctuation (another common bug), edge cases (empty string, single character), numbers, and mixed alphanumeric. The parametrized format makes it easy to see all cases at a glance and add new ones. Each case is independent — if one fails, the others still run.

> [!question]- Q3. Design a fixture structure for testing a FastAPI application with a database. Include fixtures for the app, DB connection, DB with test data, and an authenticated API client. Explain the fixture hierarchy and scopes.
**Answer:**
```python
# conftest.py
import pytest
from fastapi.testclient import TestClient
from myapp.app import create_app
from myapp.database import get_db, Session

@pytest.fixture(scope="session")
def app():
    """Create the FastAPI app once per session — app creation is expensive"""
    return create_app()

@pytest.fixture(scope="session")
def db_engine():
    """Create a test database engine once — use a separate test DB"""
    engine = create_test_engine()
    Base.metadata.create_all(engine)  # Create tables
    yield engine
    Base.metadata.drop_all(engine)  # Clean up after all tests
    engine.dispose()

@pytest.fixture
def db_session(db_engine):
    """Fresh DB session per test — transaction rolled back after each test"""
    connection = db_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)
    
    yield session
    
    # Rollback transaction — undoes all changes from the test
    transaction.rollback()
    connection.close()
    session.close()

@pytest.fixture
def test_user(db_session):
    """Create a test user — fresh for each test that needs one"""
    user = User(name="Test User", email="test@example.com")
    db_session.add(user)
    db_session.commit()
    return user

@pytest.fixture
def api_client(app, db_session):
    """API client with DB dependency overridden for testing"""
    # Override the get_db dependency to use our test session
    app.dependency_overrides[get_db] = lambda: db_session
    
    with TestClient(app) as client:
        yield client
    
    # Clear overrides after test
    app.dependency_overrides.clear()

# The hierarchy:
# app (session) → created once, shared across all tests
# db_engine (session) → created once, shared across all tests
# db_session (function) → fresh per test, transaction rolled back
# test_user (function) → depends on db_session, fresh per test
# api_client (function) → depends on app and db_session, fresh per test
#
# The key design: session-scoped fixtures for expensive setup (app, DB engine),
# function-scoped for isolated state (DB session, test data). The transaction
# rollback ensures each test sees a clean DB — no data leaks between tests.
```

> [!question]- Q4. You have a test that sometimes passes and sometimes fails (flaky test). What are the common causes, and how do you diagnose and fix each?
**Answer:** Common causes: (1) **Test order dependence** — test B relies on state left by test A. Fix: ensure each test has its own fresh fixtures, never share mutable state. (2) **Timing issues** — test assumes an async operation completes within a fixed time. Fix: use explicit waiting (retry loops) instead of `time.sleep()`, or mock the timing. (3) **External dependencies** — test calls a real API that's sometimes slow or returns different data. Fix: mock external dependencies or use a sandbox/test environment. (4) **Random data without seeding** — property-based tests or random inputs without a fixed seed. Fix: use `@given(...).examples(...)` or set a fixed random seed. (5) **Shared resources** — tests that use the same DB, file, or port. Fix: isolate resources per test or use random ports/temporary files. (6) **Cleanup failures** — previous test didn't clean up, affecting subsequent tests. Fix: use fixture teardown (`yield` pattern) for guaranteed cleanup, or `pytest.fixture(autouse=True)` for automatic cleanup. Diagnosis: run tests in isolation (`pytest test_file.py::test_name`), run tests in different orders (`pytest --random-order`), run tests multiple times (`pytest --count=10`). If a test fails only when run with others, it's isolation. If it fails randomly, it's timing or external dependency.

> [!question]- Q5. Explain the difference between `unittest.mock.patch` as a decorator, context manager, and start/stop. When would you use each?
**Answer:** `@patch("module.func")` as a decorator — patches for the duration of the test function. Cleanest syntax, automatic cleanup. Use for most cases. `with patch("module.func") as m:` as a context manager — patches only within the `with` block. Use when you need to patch for part of a test or conditionally. `patcher = patch("module.func"); mock = patcher.start(); ...; patcher.stop()` — manual start/stop. Use when you need to patch in `setUp`/`tearDown` (unittest style) or when the patch needs to span multiple test methods. The decorator is the most common and pythonic. The context manager is useful for partial or conditional patching. The start/stop pattern is for unittest compatibility or complex lifecycle management. For pytest, prefer the decorator or context manager — they integrate naturally with fixtures.

## Related
[[context-managers]]
[[exception-handling]]
[[oop-and-dunder-methods]]
[[decorators]]
[[testing-fastapi]]

#status/new