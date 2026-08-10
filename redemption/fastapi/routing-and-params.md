# Routing and Params

## What it is
FastAPI's routing maps HTTP methods and URL paths to endpoint functions. Path parameters (`/users/{user_id}`), query parameters (`?limit=10`), body parameters (JSON request body), header parameters, cookie parameters, and form parameters are all extracted from the request and injected into the endpoint function based on type hints and `Param` classes. The router system supports `APIRouter` for modular route grouping, route ordering (specific before generic), path operations with multiple methods, and WebSocket routes. This file covers the mechanics of routing, parameter extraction, and the subtle behaviors that cause 404s, 422s, and silent parameter binding bugs.

## Why it matters
Routing is the entry point of every request — if routing fails, nothing else matters. Parameter extraction is where most FastAPI errors occur (422 validation errors, missing parameters, type mismatches). Understanding how FastAPI decides which parameter comes from where (path vs query vs body) based on type hints and default values is essential for building correct APIs. In interviews, routing and parameter questions test whether you understand the extraction logic, route precedence, and the difference between required and optional parameters.

## Core example

### Route matching — order matters

```python
from fastapi import FastAPI

app = FastAPI()

# Routes are matched in the order they're defined.
# More specific routes must come before generic routes.

@app.get("/users/me")  # Specific — must come first
async def get_current_user():
    return {"user": "current"}

@app.get("/users/{user_id}")  # Generic — comes after
async def get_user(user_id: str):
    return {"user_id": user_id}

# If you reverse the order:
# /users/me would match /users/{user_id} with user_id = "me"
# The /users/me route would never be reached.

# FastAPI doesn't warn about this — it's a silent bug.
# Always define specific routes before generic routes.
# For complex routing, use APIRouter with explicit path prefixes.

# Route parameters have types — FastAPI validates during routing:
@app.get("/items/{item_id: int}")  # Only matches if item_id is an integer
async def get_item(item_id: int):
    return {"item_id": item_id}

# /items/42 → matches, item_id = 42
# /items/abc → 404 (doesn't match the int constraint)
# This is more efficient than extracting as str and converting in the function.
```

### Parameter extraction — where does each parameter come from?

```python
from fastapi import FastAPI, Path, Query, Body, Header, Cookie, Form
from pydantic import BaseModel

app = FastAPI()

class Item(BaseModel):
    name: str
    price: float

# FastAPI determines parameter source based on type hints and defaults:

@app.get("/items/{item_id}")
async def get_item(
    item_id: str,            # Path parameter (in URL path, no default = required)
    limit: int = 10,         # Query parameter (has default = optional, from ?limit=20)
    q: str | None = None,    # Query parameter (optional, can be None)
    x_header: str = Header(...),  # Header parameter (required header)
    session: str = Cookie(...),   # Cookie parameter (required cookie)
):
    # item_id: from path /items/{item_id} — required, no default
    # limit: from ?limit=20 — optional, defaults to 10
    # q: from ?q=search — optional, can be None
    # x_header: from X-Header header — required (Header(...) means required)
    # session: from session cookie — required
    ...

# The rules:
# 1. Path parameters: declared in the function signature AND in the path
#    template. Required (no default allowed — path params are always required).
# 2. Query parameters: all other parameters with defaults (or None defaults)
#    that aren't explicitly marked as Body/Header/Cookie.
# 3. Body parameters: parameters with Pydantic model types, or explicitly
#    marked with Body(). For POST/PUT/PATCH requests.
# 4. Header parameters: explicitly marked with Header().
# 5. Cookie parameters: explicitly marked with Cookie().
# 6. Form parameters: explicitly marked with Form() — for form data, not JSON.

# The key insight: FastAPI uses type hints + defaults to infer the source.
# If you don't want inference, use the explicit Param classes.
```

### Path parameters — constraints and types

```python
from fastapi import FastAPI, Path

app = FastAPI()

# Path parameters can have validation constraints:
@app.get("/items/{item_id}")
async def get_item(
    item_id: int = Path(..., gt=0, le=1000),  # 0 < item_id <= 1000
    q: str = Query(None, min_length=3, max_length=50),
):
    return {"item_id": item_id}

# Path constraints:
# gt, ge, lt, le — numeric comparisons
# min_length, max_length — string length
# regex — pattern match (uses Python re module)

# /items/0 → 422 (gt=0 fails)
# /items/1001 → 422 (le=1000 fails)
# /items/abc → 422 (int conversion fails)

# Multiple path parameters:
@app.get("/users/{user_id}/posts/{post_id}")
async def get_user_post(user_id: int, post_id: int):
    return {"user_id": user_id, "post_id": post_id}

# Path parameters are extracted from the URL path during routing.
# They're always required — you can't have an optional path parameter.
# If you need an optional "path-like" parameter, use a query parameter instead.
```

### Query parameters — complex structures

```python
from typing import Annotated
from fastapi import FastAPI, Query

app = FastAPI()

# Multiple values for the same query param: ?tag=python&tag=fastapi
@app.get("/items/")
async def search_items(tag: list[str] = Query(default=["default_tag"])):
    # tag = ["python", "fastapi"] for ?tag=python&tag=fastapi
    return {"tag": tag}

# Fixed values — only specific values allowed
@app.get("/items/")
async def search_items(
    sort: str = Query(default="asc", options=["asc", "desc"]),
):
    # Only "asc" or "desc" allowed — any other value → 422
    return {"sort": sort}

# Alias — different name in query vs function parameter
@app.get("/items/")
async def search_items(
    page: int = Query(1, alias="page-number"),  # ?page-number=5
):
    return {"page": page}

# Deprecate a query parameter
@app.get("/items/")
async def search_items(
    old_param: str = Query(None, deprecated=True),
):
    # old_param still works but OpenAPI docs mark it as deprecated
    # Clients see a warning in the API docs
    return {"old_param": old_param}

# Required query parameter (no default)
@app.get("/items/")
async def search_items(q: str):  # No default = required
    # ?q=hello → works
    # (no q) → 422 (missing required query parameter)
    return {"q": q}
```

### Body parameters — JSON, form, and file uploads

```python
from fastapi import FastAPI, Body, Form, File, UploadFile
from pydantic import BaseModel

app = FastAPI()

class Item(BaseModel):
    name: str
    price: float
    tags: list[str] = []

# JSON body — Pydantic model (most common)
@app.post("/items/")
async def create_item(item: Item):
    # FastAPI parses the JSON body, validates against Item model,
    # and passes the validated object to the function.
    # If validation fails → 422 with detailed error messages.
    return item

# Multiple body parameters — use Body(embed=True)
@app.post("/items/")
async def create_item(
    item: Item,
    importance: int = Body(..., gt=0, embedded=True),
    # Without embed: {"item": {...}, "importance": 5}
    # With embed: importance is at top level alongside item fields
    # Actually: embed=True makes importance a top-level field in the same body
    # Both item fields and importance are in the same JSON body
    ...
):
    ...

# Form data — application/x-www-form-urlencoded
@app.post("/login/")
async def login(username: str = Form(...), password: str = Form(...)):
    # Expects form data, not JSON
    # Content-Type: application/x-www-form-urlencoded
    return {"username": username}

# File uploads — multipart/form-data
@app.post("/upload/")
async def upload(file: UploadFile = File(...)):
    # UploadFile has .file (SpooledTemporaryFile), .filename, .content_type
    # content = await file.read()  # Async read — doesn't block
    return {"filename": file.filename}

# Multiple files
@app.post("/upload/")
async def upload(files: list[UploadFile] = File(...)):
    # Multiple files with same field name
    return {"count": len(files), "filenames": [f.filename for f in files]}

# File + form fields together
@app.post("/upload/")
async def upload(
    file: UploadFile = File(...),
    description: str = Form(...),
):
    # Both file and form fields in the same multipart request
    return {"filename": file.filename, "description": description}
```

### APIRouter — modular route grouping

```python
from fastapi import APIRouter, FastAPI

# APIRouter allows you to group routes by feature/module.
# Each router can have its own prefix, tags, dependencies, and responses.

# users.py
user_router = APIRouter(
    prefix="/users",
    tags=["users"],
    dependencies=[],  # Applied to all routes in this router
    responses={404: {"description": "Not found"}},
)

@user_router.get("/", response_model=list[User])
async def list_users():
    ...

@user_router.get("/{user_id}", response_model=User)
async def get_user(user_id: int):
    ...

@user_router.post("/", response_model=User, status_code=201)
async def create_user(user: UserCreate):
    ...

# posts.py
post_router = APIRouter(prefix="/posts", tags=["posts"])

@post_router.get("/", response_model=list[Post])
async def list_posts():
    ...

# main.py
app = FastAPI()

app.include_router(user_router)   # Routes: /users/, /users/{id}
app.include_router(post_router)   # Routes: /posts/, /posts/{id}

# You can also add prefix at include time:
# app.include_router(user_router, prefix="/api/v1/users")
# This adds another prefix on top of the router's prefix.

# APIRouter is essential for:
# - Large applications with many endpoints
# - Versioning (/api/v1/users, /api/v2/users)
# - Team ownership (different teams own different routers)
# - Conditional mounting (mount admin router only in certain environments)
# - Shared dependencies (auth on all routes in a router)
```

### Route ordering and 404s — common pitfalls

```python
# Pitfall 1: Generic before specific (already covered — silent 404)

# Pitfall 2: Method not allowed
@app.get("/items/")
async def list_items():
    ...

# POST /items/ → 405 Method Not Allowed (not 404)
# FastAPI returns 405 when the path exists but the method doesn't.
# The response includes an Allow header with allowed methods.

# Pitfall 3: Trailing slash
@app.get("/items")
async def get_items():
    ...

# GET /items/ → 404 (different path — trailing slash matters)
# FastAPI doesn't redirect by default. You can configure redirect:
# app = FastAPI(redirect_slashes=True)  # Default is True
# With redirect: /items/ → 307 → /items

# Pitfall 4: Path parameter type mismatch
@app.get("/items/{item_id}")
async def get_item(item_id: int):
    ...

# GET /items/abc → 422 (validation error, not 404)
# The route matches (path pattern matches), but the int conversion fails.
# This is a 422 (validation error), not 404 (not found).
# 404 = no route matches. 422 = route matches but params invalid.

# Pitfall 5: Query parameter name collision
@app.get("/items/")
async def get_items(skip: int = 0, limit: int = 10):
    ...

# If you have a Pydantic model with a field named "skip" and you
# use it as a body parameter, the query param "skip" and body field
# "skip" are in different locations — no collision. But if you
# use the same name for query and path parameters, the path param
# takes precedence (it's required and in the URL).
```

## Common mistakes / gotchas

- **Generic route before specific route** — the generic route matches first, making the specific route unreachable. Always define specific routes first. FastAPI doesn't warn about this.
- **Confusing 404 and 422** — 404 means no route matches. 422 means the route matches but parameter validation failed. If you get 422 on a path parameter, check the type constraint (e.g., int vs string).
- **Forgetting that path parameters are required** — you can't have an optional path parameter. If you need optional, use a query parameter instead.
- **Body parameter inference confusion** — FastAPI infers body parameters from Pydantic model types. If you have a function with both a Pydantic model and a simple type with a default, the simple type becomes a query parameter, not a body field. Use `Body(embed=True)` to force it into the body.
- **File uploads with sync file operations** — `UploadFile.read()` is async. Don't use synchronous file operations on the uploaded file — use `await file.read()` and `await file.seek()`. For large files, use `SpooledTemporaryFile` or stream to disk.
- **Form data vs JSON body** — `Form()` expects `application/x-www-form-urlencoded` or `multipart/form-data`, not JSON. If you send JSON to a Form endpoint, you get 422. If you send form data to a JSON endpoint, you get 422. Match the Content-Type to the parameter type.
- **APIRouter dependency ordering** — dependencies on a router apply to all routes in the router. If you add a dependency at the router level and also at the route level, both run (router deps first, then route deps). Be careful about order — auth should run before business logic.
- **Path parameter naming conflicts** — you can't have two routes with the same path pattern but different parameter names (`/users/{id}` and /users/{user_id}`) — they conflict. Use consistent naming across your API.

## Practice

> [!question]- Q1. Design a RESTful API for a blog with users, posts, and comments. Use APIRouter for modularity, proper path parameters, and query parameters for pagination/filtering. Show the router structure and key endpoints.
**Answer:**
```python
# routers/users.py
user_router = APIRouter(prefix="/users", tags=["users"])

@user_router.get("/", response_model=list[User])
async def list_users(skip: int = 0, limit: int = Query(10, le=100)):
    ...

@user_router.get("/{user_id}", response_model=User)
async def get_user(user_id: int):
    ...

@user_router.post("/", response_model=User, status_code=201)
async def create_user(user: UserCreate):
    ...

# routers/posts.py
post_router = APIRouter(prefix="/posts", tags=["posts"])

@post_router.get("/", response_model=list[Post])
async def list_posts(
    skip: int = 0,
    limit: int = Query(10, le=100),
    user_id: int | None = None,  # Filter by author
    tag: str | None = None,      # Filter by tag
):
    ...

@post_router.get("/{post_id}", response_model=PostWithComments)
async def get_post(post_id: int, deep: bool = False):
    ...

@post_router.post("/{post_id}/comments/", response_model=Comment, status_code=201)
async def create_comment(post_id: int, comment: CommentCreate):
    ...

# main.py
app = FastAPI()
app.include_router(user_router)
app.include_router(post_router)
```
Key design decisions: nested resource for comments on posts (`/posts/{id}/comments/`) because comments don't exist independently of posts. Pagination via query params (skip, limit) with a max limit to prevent abuse. Filtering via optional query params. Path parameters use consistent naming (user_id, post_id). Status codes: 200 for GET, 201 for POST. Response models vary by endpoint (list vs single vs with comments).

> [!question]- Q2. An endpoint accepts a JSON body with a nested object. The client sends the body but FastAPI returns 422 with "field required" for a field that's clearly in the JSON. Diagnose and fix.
**Answer:** Common causes: (1) **Field name mismatch** — the JSON key is `user_id` but the Pydantic model has `userId` (snake_case vs camelCase). Fix: use `alias` in Pydantic `Field(alias="userId")` or configure `model_config = ConfigDict(populate_by_name=True)` and `alias_generator`. (2) **Nested object structure** — the client sends `{"user": {"name": "Alice"}}` but the model expects `{"name": "Alice"}` at the top level. Fix: check the model structure matches the JSON structure. (3) **Content-Type mismatch** — the client sends `text/plain` instead of `application/json`. FastAPI doesn't parse the body as JSON. Fix: ensure Content-Type: application/json. (4) **Extra fields** — the model has `extra="forbid"` and the client sends extra fields. Fix: set `extra="ignore"` or `extra="allow"` in model config, or remove extra fields from the request. (5) **Type mismatch** — the JSON has `"age": "25"` (string) but the model expects `age: int`. Fix: send correct types or use a validator to coerce. Diagnosis: look at the 422 response body — it lists the exact validation errors with locations and messages. The error message tells you exactly which field failed and why.

> [!question]- Q3. You need to support both REST (`/users/1`) and RPC-style (`/users?action=get&id=1`) URL patterns for backward compatibility. How do you handle this in FastAPI?
**Answer:** Create two route definitions that point to the same handler:
```python
@app.get("/users/{user_id}")
async def get_user_rest(user_id: int):
    return await get_user_by_id(user_id)

@app.get("/users")
async def get_user_rpc(action: str, user_id: int | None = None):
    if action == "get" and user_id is not None:
        return await get_user_by_id(user_id)
    raise HTTPException(400, "Invalid RPC parameters")
```
The REST route handles the modern path-based approach. The RPC route handles the legacy query-based approach. Both call the same internal function. For a cleaner approach, use APIRouter with a shared dependency that extracts the user ID from either source:
```python
def get_user_id(user_id: int | None = None, request: Request = None):
    # Try path param first, then query param
    if user_id is not None:
        return user_id
    if request:
        return int(request.query_params.get("user_id"))
    raise HTTPException(400, "User ID required")
```
The key principle: support multiple URL patterns by mapping them to the same handler logic. Don't duplicate the business logic — extract it into a shared function and have both routes call it.

> [!question]- Q4. Explain the difference between path parameters, query parameters, and body parameters in terms of: (1) where they come from in the HTTP request, (2) whether they can be optional, (3) how they're validated, and (4) their typical use cases.
**Answer:** (1) **Source**: Path parameters come from the URL path segments (`/users/{id}`). Query parameters come from the URL query string (`?limit=10`). Body parameters come from the request body (JSON, form, or multipart). (2) **Optionality**: Path parameters are always required (no default allowed). Query parameters can be optional (with defaults). Body parameters can be required or optional depending on the model field defaults. (3) **Validation**: Path parameters are validated during routing (type constraints, regex). Query parameters are validated by Query() constraints (min/max, length, regex). Body parameters are validated by Pydantic model validation (type checking, field constraints, custom validators). All produce 422 errors on validation failure. (4) **Use cases**: Path parameters for resource identifiers (required, part of the resource identity). Query parameters for filtering, sorting, pagination, optional search criteria. Body parameters for creating/updating resources, complex input data. The REST convention: path = what resource, query = how to filter it, body = what to change/create.

> [!question]- Q5. You have an endpoint that should accept either a JSON body OR query parameters, but not both. How do you implement this in FastAPI?
**Answer:** FastAPI doesn't natively support "either/or" parameter sources. You need custom validation:
```python
from fastapi import Request, HTTPException

@app.post("/search/")
async def search(
    request: Request,
    query: str | None = None,
    body: SearchRequest | None = None,
):
    # Check that exactly one of query or body is provided
    has_query = query is not None
    has_body = body is not None
    
    if has_query == has_body:  # Both or neither
        raise HTTPException(400, "Provide either query param or JSON body, not both")
    
    if has_query:
        # Search using query param
        return search_by_query(query)
    else:
        # Search using body
        return search_by_request(body)
```
The key: both parameters are optional, and you add runtime validation to enforce the mutual exclusivity. FastAPI can't express this in type hints alone because parameter source (query vs body) is independent of optionality. Alternative: use a single endpoint that reads the raw request and decides based on Content-Type or presence of body — but this loses FastAPI's auto-validation and docs. The explicit parameter approach with runtime validation is cleaner and preserves OpenAPI docs.

## Related
[[request-response-lifecycle]]
[[pydantic-models-and-validation]]
[[dependency-injection]]
[[error-handling-and-exception-handlers]]
[[api-versioning]]

#status/new