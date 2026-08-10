# Error Handling and Exception Handlers

## What it is
FastAPI's exception handling system lets you define custom responses for specific exception types, overriding the default behavior. When an exception is raised anywhere in the request lifecycle (endpoint, dependency, middleware), FastAPI looks for a registered exception handler and uses it to build the response. This file covers built-in exceptions, custom exception handlers, the difference between HTTPException and custom exceptions, exception handling in dependencies and middleware, and the patterns that produce consistent, informative error responses.

## Why it matters
A well-designed error response tells the client exactly what went wrong and how to fix it. A poorly designed one either leaks internal details (stack traces, database errors) or is too vague ("something went wrong"). In production, error handling is critical for debugging, client experience, and security. In interviews, error handling questions test whether you understand exception propagation, the difference between 4xx and 500 errors, and how to build consistent error responses. For your work — any API that clients depend on — error handling is a first-class concern.

## Core example

### HTTPException — the built-in standard

```python
from fastapi import FastAPI, HTTPException

app = FastAPI()

# HTTPException is the standard way to return error responses
# It takes a status_code and an optional detail message

@app.get("/items/{item_id}")
async def get_item(item_id: int):
    if item_id < 0:
        # 400 Bad Request — client error
        raise HTTPException(status_code=400, detail="Item ID must be positive")
    
    item = await db.get(item_id)
    if item is None:
        # 404 Not Found — resource doesn't exist
        raise HTTPException(status_code=404, detail="Item not found")
    
    # Check permissions
    if not can_access(current_user, item):
        # 403 Forbidden — authenticated but not authorized
        raise HTTPException(status_code=403, detail="Access denied")
    
    return item

# HTTPException also supports headers:
@app.get("/rate-limited/")
async def rate_limited():
    if rate_limit_exceeded:
        raise HTTPException(
            status_code=429,  # Too Many Requests
            detail="Rate limit exceeded",
            headers={"Retry-After": "60"},  # Tell client when to retry
        )
    return {"data": "ok"}

# The detail field can be any JSON-serializable value:
@app.get("/validation-error/")
async def validation_error():
    raise HTTPException(
        status_code=422,
        detail={
            "errors": [
                {"field": "email", "message": "Invalid email format"},
                {"field": "password", "message": "Must be at least 8 characters"},
            ]
        },
    )
```

### Custom exception classes — domain-specific errors

```python
from fastapi import HTTPException

# Custom exception classes make your code more expressive and
# allow centralized handling via exception handlers.

class AppException(Exception):
    """Base application exception — all custom exceptions inherit from this"""
    def __init__(self, status_code: int, detail: str | dict = None, code: str = None):
        self.status_code = status_code
        self.detail = detail or self.__class__.__name__
        self.code = code or self.__class__.__name__.lower()

class NotFoundException(AppException):
    """Resource not found"""
    def __init__(self, detail: str = "Resource not found"):
        super().__init__(status_code=404, detail=detail, code="not_found")

class ForbiddenException(AppException):
    """Access forbidden"""
    def __init__(self, detail: str = "Access forbidden"):
        super().__init__(status_code=403, detail=detail, code="forbidden")

class ValidationException(AppException):
    """Input validation failed"""
    def __init__(self, detail: str | dict = "Validation failed"):
        super().__init__(status_code=422, detail=detail, code="validation")

class ConflictException(AppException):
    """Resource conflict (e.g., duplicate email)"""
    def __init__(self, detail: str = "Resource conflict"):
        super().__init__(status_code=409, detail=detail, code="conflict")

class RateLimitException(AppException):
    """Rate limit exceeded"""
    def __init__(self, retry_after: int = 60):
        super().__init__(
            status_code=429,
            detail="Rate limit exceeded",
            code="rate_limit",
        )
        self.headers = {"Retry-After": str(retry_after)}

class ServiceException(AppException):
    """Internal service error"""
    def __init__(self, detail: str = "Internal server error"):
        super().__init__(status_code=500, detail=detail, code="service_error")

# Usage in endpoints:
@app.get("/users/{user_id}")
async def get_user(user_id: int):
    user = await db.get_user(user_id)
    if user is None:
        raise NotFoundException(f"User with ID {user_id} not found")
    
    if not current_user.can_access(user):
        raise ForbiddenException("You don't have access to this user")
    
    return user

# The advantage over HTTPException:
# - More expressive intent (NotFoundException vs HTTPException(404))
# - Consistent error structure (all have status_code, detail, code)
# - Can add custom fields (headers, error code, metadata)
# - Centralized handling via exception handlers
```

### Exception handlers — customizing the response format

```python
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

# Register exception handlers on the FastAPI app

# Handler for custom AppException (and all subclasses)
async def app_exception_handler(request: Request, exc: AppException):
    # Build a consistent error response
    response_data = {
        "error": exc.code,
        "message": exc.detail,
        "path": str(request.url),
        "method": request.method,
    }
    
    # Include headers if the exception has them
    headers = getattr(exc, "headers", {})
    
    return JSONResponse(
        status_code=exc.status_code,
        content=response_data,
        headers=headers,
    )

# Handler for Pydantic validation errors (422 from request body/query)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    # Format Pydantic errors in a cleaner way
    errors = []
    for err in exc.errors():
        # Location: body.field, query.param, path.param
        location = err["loc"][0] if err["loc"] else "unknown"
        field = ".".join(str(loc) for loc in err["loc"][1:]) if len(err["loc"]) > 1 else "unknown"
        
        errors.append({
            "location": location,
            "field": field,
            "message": err["msg"],
            "code": err["type"],
            "input": err.get("input"),  # The invalid value
        })
    
    response_data = {
        "error": "validation",
        "message": "Request validation failed",
        "errors": errors,
        "path": str(request.url),
        "method": request.method,
    }
    
    return JSONResponse(status_code=422, content=response_data)

# Handler for unhandled exceptions (500 — should never expose details)
async def unhandled_exception_handler(request: Request, exc: Exception):
    # Log the full error for debugging (but don't expose to client)
    logger.error(f"Unhandled error on {request.method} {request.url}", exc_info=True)
    
    # Generic error response — never leak internals
    response_data = {
        "error": "internal_error",
        "message": "An internal error occurred",
        "path": str(request.url),
        "method": request.method,
    }
    
    # In development, you might want to include the error:
    # if settings.debug:
    #     response_data["debug"] = str(exc)
    
    return JSONResponse(status_code=500, content=response_data)

# Register all handlers in main.py:
app = FastAPI()

app.add_exception_handler(AppException, app_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)  # Catch-all
```

### Exception handling in dependencies and middleware

```python
# Exceptions raised in dependencies propagate to exception handlers
# just like exceptions in endpoints.

async def get_admin_user(current_user: User = Depends(get_current_user)):
    if current_user.role != "admin":
        raise ForbiddenException("Admin only")  # Caught by handler
    return current_user

# If a dependency raises an exception, the endpoint is never called.
# The exception is caught by the registered exception handler.
# This is the standard pattern for auth/authorization failures.

# Exceptions in middleware — different behavior
@app.middleware("http")
async def error_handling_middleware(request: Request, call_next):
    try:
        response = await call_next(request)
        # If an exception is raised in the endpoint or dependency,
        # it's caught by FastAPI's exception handlers BEFORE reaching
        # the response phase of middleware.
        # So you won't see the exception here — you see the response
        # that the exception handler produced.
        return response
    except Exception as e:
        # This catches exceptions from middleware itself,
        # NOT from the endpoint/dependencies.
        # For endpoint exceptions, use exception handlers.
        logger.error(f"Middleware error: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"error": "middleware_error"})

# If you need to catch ALL exceptions (including from endpoints)
# in middleware, you need to wrap call_next and handle the exception.
# But this bypasses FastAPI's exception handlers — not recommended.
# Use exception handlers for endpoint/dependency exceptions.
# Use middleware for middleware-level exceptions only.
```

### The exception handling pipeline — order of resolution

```python
# When an exception is raised during request processing:
# 1. Check if there's an exact exception type handler registered
#    (app.add_exception_handler(SomeException, handler))
# 2. If not, check parent class handlers (inheritance chain)
# 3. If no custom handler, use FastAPI's default handler:
#    - HTTPException → response with status code and detail
#    - RequestValidationError → 422 with validation errors
#    - Other exceptions → 500 with internal error
# 4. The response goes through middleware (response phase)
# 5. Response is sent to client

# Important: exception handlers are checked in order of specificity.
# A handler for AppException also handles NotFoundException (subclass).
# But a handler for NotFoundException takes precedence over AppException
# for NotFoundException instances.

# You can register multiple handlers for different exception types:
app.add_exception_handler(NotFoundException, not_found_handler)
app.add_exception_handler(ForbiddenException, forbidden_handler)
app.add_exception_handler(AppException, app_exception_handler)  # Fallback
app.add_exception_handler(Exception, unhandled_exception_handler)  # Last resort

# The most specific handler wins. AppException handler catches all
# AppException subclasses that don't have their own handler.
# The Exception handler catches everything else (including non-AppException).
```

### Error response design — what makes a good error

```python
# Bad error response — too vague:
# {"detail": "Not found"}

# Bad error response — leaks internals:
# {"detail": "ProgrammingError: relation 'users' does not exist\n..."}

# Good error response — consistent, informative, safe:
{
  "error": "not_found",          # Machine-readable error code
  "message": "User 42 not found", # Human-readable message
  "path": "/api/v1/users/42",    # Request path
  "method": "GET",               # HTTP method
  "timestamp": "2024-01-01T00:00:00Z",  # When it happened
  "request_id": "abc-123-xyz",   # Correlation ID for tracing
  "details": [                   # Optional, structured details
    {
      "field": "user_id",
      "message": "No user with this ID exists",
      "code": "user.not_found"
    }
  ]
}

# For validation errors — list all errors at once:
{
  "error": "validation",
  "message": "Request validation failed",
  "errors": [
    {
      "location": "body",
      "field": "email",
      "message": "value is not a valid email address",
      "code": "value_error.email",
      "input": "not-an-email"
    },
    {
      "location": "body",
      "field": "password",
      "message": "ensure this value has at least 8 characters",
      "code": "value_error.any_str.min_length",
      "input": "123"
    }
  ],
  "path": "/api/v1/users",
  "method": "POST"
}

# Key principles for error response design:
# 1. Consistent structure — every error has the same fields
# 2. Machine-readable error code — clients can programmatically handle errors
# 3. Human-readable message — explains what went wrong
# 4. No internal details — don't leak stack traces, SQL, or internal paths
# 5. Include request context — method, path, request_id for debugging
# 6. List ALL validation errors at once — don't stop at the first one
# 7. Include the invalid input value — helps clients debug
# 8. Use standard HTTP status codes — 400, 401, 403, 404, 409, 422, 429, 500
```

## Common mistakes / gotchas

- **Raising plain exceptions instead of HTTPException** — `raise Exception("something")` returns 500 with a generic message. Use HTTPException or custom exceptions with proper status codes for client errors.
- **Not having a catch-all exception handler** — without a handler for `Exception`, unhandled exceptions return FastAPI's default 500 response, which may include stack traces in debug mode. Always register a catch-all handler that returns a safe, generic error.
- **Leaking internal details in error messages** — database errors, stack traces, file paths, and internal service names should never reach the client. Log them server-side, return generic messages to the client.
- **Inconsistent error responses** — different endpoints return different error formats. This makes client-side error handling impossible. Use a centralized exception handler for consistent formatting.
- **Raising exceptions in middleware without handling** — if middleware raises an exception and there's no handler, FastAPI returns a 500. But the exception bypasses the normal exception handling pipeline. Handle exceptions in middleware or let them propagate to exception handlers.
- **Not logging unhandled exceptions** — if you have a catch-all handler that returns a generic 500, make sure it logs the full exception (with traceback) for debugging. Otherwise, you're flying blind in production.
- **Using exception handlers for control flow** — exceptions should be for exceptional conditions, not normal control flow. Using exceptions for expected conditions (like "user not found" as part of login flow) is an anti-performance and anti-pattern. Use regular condition checks for expected conditions.
- **Forgetting that Pydantic validation errors are already handled** — FastAPI has a built-in handler for RequestValidationError (422 from Pydantic). If you register your own, you're overriding the default. Make sure your handler provides a better experience, not just a different format.

## Practice

> [!question]- Q1. Design an error handling strategy for a FastAPI API that serves both web clients (browser) and API clients (mobile app, third-party integrators). The error responses need to work for both.
**Answer:** The key insight: web clients need human-readable messages for display, API clients need machine-readable error codes for programmatic handling. Design a response that serves both:
```python
{
  "error": "validation",           # Machine-readable code
  "message": "Validation failed",  # Human-readable summary
  "errors": [...],                 # Detailed per-field errors
  "request_id": "...",             # For support/debugging
  "documentation_url": "https://docs.example.com/errors/validation"  # For developers
}
```
Web clients display `message` and `errors[].message`. API clients check `error` code and handle programmatically. Third-party integrators use `documentation_url` for reference. The `request_id` is for support — users can report it and you can look up the full error in logs. For web-specific errors (e.g., redirect to login on 401), use a middleware that checks the Accept header and returns a redirect for browser requests and JSON for API requests. The key: one error format that serves all clients, with both human and machine-readable fields.

> [!question]- Q2. An endpoint raises a custom exception inside a dependency. The dependency is used by 10 endpoints. Explain the exception propagation path and where it's handled.
**Answer:** The exception path: (1) Dependency function raises the custom exception. (2) FastAPI catches the exception during dependency resolution. (3) The endpoint function is NOT called (short-circuited). (4) FastAPI looks for a registered exception handler for the exception type (exact match first, then parent class). (5) The handler builds a response (JSONResponse with appropriate status code and body). (6) The response goes through the middleware stack (response phase). (7) The response is sent to the client. The exception is handled by the registered exception handler — it doesn't propagate to the endpoint or to the caller of the dependency. This is why dependencies are a clean place for auth/authorization checks: if the check fails, the exception is caught and a proper error response is returned without the endpoint ever running. The 10 endpoints that use this dependency all benefit from the same exception handling — no need to repeat the error handling logic in each endpoint.

> [!question]- Q3. You have a microservices architecture. Service A calls Service B. Service B returns a 500 error. How should Service A handle this when returning a response to its own client?
**Answer:** Service A should NOT propagate Service B's raw error to its client. Instead: (1) Catch the exception from the HTTP call to Service B. (2) Log the full error (including Service B's response) for debugging. (3) Determine the appropriate HTTP status code for Service A's client: if Service B's error is temporary (503, timeout), return 503 with a retry-after header. If Service B's error indicates the requested resource doesn't exist, return 404. If Service B's error is a validation error from Service B, return 422 with a translated error message. (4) Return a generic, safe error response to the client — don't expose Service B's internal error details. (5) Include a request_id that correlates across services for distributed tracing. The key principle: each service owns its error responses. Downstream errors are translated into the service's own error format. The client of Service A should never see Service B's internal errors. For production: use circuit breakers to prevent cascading failures — if Service B is consistently failing, Service B should fail fast instead of timing out, and Service A should return a degraded response or cached data if available.

> [!question]- Q4. Explain the difference between raising `HTTPException(status_code=404)` vs returning `JSONResponse(content={"error": "not found"}, status_code=404)`. When would you use each?
**Answer:** `HTTPException(status_code=404, detail="...")` is an exception that triggers FastAPI's exception handling pipeline. It's caught by the HTTPException handler (built-in or custom) and converted to a response. The key: the exception propagates up the call stack — it can be raised from anywhere (endpoint, dependency, middleware) and is caught by the nearest handler. `JSONResponse(...)` is a direct response — it immediately returns an HTTP response without going through exception handling. Use `HTTPException` when: you want to signal an error condition that should be handled by the exception handler, you're in a dependency or deep in the call stack and can't directly return a response, you want consistent error formatting via exception handlers. Use `JSONResponse` when: you want to return a non-error response with a specific status code (e.g., 201 Created, 204 No Content), you're in a middleware and need to short-circuit with a custom response, you want full control over the response body and don't want the exception handler to format it. The rule: exceptions for errors, responses for everything else. But even for errors, use HTTPException (or custom exceptions) for consistency, not direct JSONResponse.

> [!question]- Q5. Your FastAPI API has an endpoint that sometimes raises a custom `RateLimitException` with a `Retry-After` header. Design the exception handler so that the header is included in the response, and explain how you'd test this.
**Answer:**
```python
async def rate_limit_handler(request: Request, exc: RateLimitException):
    response_data = {
        "error": "rate_limit",
        "message": exc.detail,
        "retry_after": exc.retry_after,  # Include in body too
        "path": str(request.url),
    }
    
    headers = {"Retry-After": str(exc.retry_after)}
    
    return JSONResponse(
        status_code=429,
        content=response_data,
        headers=headers,
    )

app.add_exception_handler(RateLimitException, rate_limit_handler)

# Testing with TestClient:
from fastapi.testclient import TestClient

client = TestClient(app)

# Test 1: Check status code
response = client.get("/rate-limited-endpoint/")
assert response.status_code == 429

# Test 2: Check header
assert response.headers["Retry-After"] == "60"

# Test 3: Check body
data = response.json()
assert data["error"] == "rate_limit"
assert data["retry_after"] == 60

# Test 4: Simulate rate limit by making multiple requests
for _ in range(10):
    client.get("/api/endpoint/")
response = client.get("/api/endpoint/")
assert response.status_code == 429
assert response.headers["Retry-After"] is not None

# The key: the exception handler sets both the response body and
# the headers. The TestClient allows checking both. For production,
# the Retry-After header tells clients (and load balancers) when
# to retry, and the body provides a machine-readable error code.
```

## Related
[[request-response-lifecycle]]
[[middleware]]
[[dependency-injection]]
[[pydantic-models-and-validation]]
[[logging-and-monitoring]]

#status/new