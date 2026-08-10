# API Versioning

## What it is
API versioning is the strategy for evolving your API over time without breaking existing clients. When you add fields, change response shapes, modify validation rules, or deprecate endpoints, existing clients that depend on the old behavior break. Versioning gives you a way to introduce changes while maintaining backward compatibility. This file covers versioning strategies (URL, header, content negotiation), deprecation policies, backward vs forward compatibility, and the practical patterns for managing multiple API versions in FastAPI.

## Why it matters
Every API evolves. If you don't version, you force all clients to update simultaneously — which is impossible for public APIs with third-party clients. In interviews, API design questions test whether you understand versioning strategies, backward compatibility, and deprecation. For your work — if your API is used by other teams, mobile apps, or external developers — versioning is not optional. It's the difference between an API that clients trust and one they fear.

## Core example

### Versioning strategies — comparison

```python
# Strategy 1: URL Path Versioning (most common, most explicit)
# GET /api/v1/users/
# GET /api/v2/users/

# Pros: explicit, visible in logs and docs, easy to debug,
#       CDN caching works (different URLs = different cache keys)
# Cons: URL changes on every version, "REST purists" hate it,
#       requires route duplication or router mounting

# FastAPI implementation:
from fastapi import APIRouter

# v1 router
router_v1 = APIRouter(prefix="/api/v1")

@router_v1.get("/users/", response_model=UserV1)
async def list_users_v1():
    ...

# v2 router
router_v2 = APIRouter(prefix="/api/v2")

@router_v2.get("/users/", response_model=UserV2)
async def list_users_v2():
    ...

app.include_router(router_v1)
app.include_router(router_v2)

# Strategy 2: Header Versioning (cleaner URLs)
# GET /users/
# Header: X-API-Version: 2
# or Header: Accept: application/vnd.myapi.v2+json

# Pros: clean URLs, follows HTTP semantics (content negotiation),
#       URLs don't change between versions
# Cons: less visible (harder to debug), CDN caching doesn't
#       distinguish versions (same URL), requires middleware
#       to parse version and route

# FastAPI implementation:
@app.middleware("http")
async def version_middleware(request: Request, call_next):
    # Extract version from header
    version = request.headers.get("X-API-Version", "1")
    request.state.api_version = version
    
    # Or from Accept header:
    # accept = request.headers.get("Accept", "")
    # if "v2" in accept: version = "2"
    
    response = await call_next(request)
    response.headers["X-API-Version"] = version
    return response

# In endpoint, check version:
@app.get("/users/")
async def list_users(request: Request):
    version = request.state.api_version
    
    if version == "1":
        return await list_users_v1()
    elif version == "2":
        return await list_users_v2()
    else:
        raise HTTPException(400, f"Unsupported API version: {version}")

# Strategy 3: Content Negotiation (most RESTful)
# Accept: application/vnd.myapi.v1+json
# Accept: application/vnd.myapi.v2+json

# Pros: follows HTTP content negotiation semantics, clean URLs,
#       explicit media type in Accept header
# Cons: complex to implement, less intuitive for developers,
#       tools (Postman, curl) need custom headers

# FastAPI implementation with custom media type:
@app.get("/users/")
async def list_users(request: Request):
    accept = request.headers.get("Accept", "application/vnd.myapi.v1+json")
    
    # Parse version from media type
    match = re.search(r"v(\d+)", accept)
    version = match.group(1) if match else "1"
    
    if version == "1":
        return await list_users_v1()
    elif version == "2":
        return await list_users_v2()
    else:
        raise HTTPException(406, f"Unsupported Accept header: {accept}")

# Strategy 4: Query Parameter Versioning (simple but discouraged)
# GET /users/?version=2
# GET /users/?v=2

# Pros: simple, visible in URL, easy to test
# Cons: pollutes query parameters, not RESTful, caching issues,
#       can conflict with other query parameters
# NOT recommended for production APIs.

# Recommendation: URL path versioning for public/external APIs
# (explicit, cacheable, easy to debug). Header versioning for
# internal APIs (clean URLs, controlled clients). Avoid query
# parameter versioning.
```

### Backward vs forward compatibility — the critical distinction

```python
# Backward compatibility: new server works with old clients.
# You add a field to the response. Old clients ignore the new field
# and continue working. This is the most important compatibility.

# Forward compatibility: old server works with new clients.
# You add a field to the request. Old server ignores the new field
# and processes the request. This is harder and less common.

# Rules for backward-compatible changes (SAFE to do):
# 1. Add new optional fields to requests (with defaults)
# 2. Add new fields to responses (old clients ignore them)
# 3. Add new endpoints (old clients don't call them)
# 4. Add new optional query parameters (with defaults)
# 5. Extend enum values (add new allowed values)
# 6. Make fields longer (increase max_length)
# 7. Add new error codes (old clients treat as generic error)

# Rules for breaking changes (REQUIRE a new version):
# 1. Remove fields from requests or responses
# 2. Change field types (string → integer)
# 3. Rename fields (old clients can't find them)
# 4. Make optional fields required
# 5. Change endpoint URLs or HTTP methods
# 6. Change validation rules (stricter validation rejects old requests)
# 7. Change error response format
# 8. Remove endpoints

# The golden rule: if it breaks an existing client, it's a new version.
# If old clients continue to work, it's a backward-compatible change.

# Example — backward-compatible evolution:
# v1:
class UserV1(BaseModel):
    id: int
    name: str
    email: str

# v2 (backward-compatible additions):
class UserV2(BaseModel):
    id: int
    name: str
    email: str
    phone: str | None = None  # New optional field
    created_at: str | None = None  # New field
    # Old clients ignore phone and created_at — they still work

# Example — breaking change (needs new version):
# v1:
class UserV1(BaseModel):
    id: int
    full_name: str  # Single field

# v2 (breaking — can't do this in v1):
class UserV2(BaseModel):
    id: int
    first_name: str  # Split into two fields
    last_name: str
    # Old clients expect full_name — they break!
    # Solution: new version /api/v2/users/ with new response model
```

### Deprecation policy — the responsible way to remove features

```python
# You can't remove features overnight. Clients need time to migrate.
# A deprecation policy gives clients a clear timeline.

# Deprecation stages:
# 1. Announced — documented as deprecated, no functional change
# 2. Deprecated — warnings in responses, documentation updated
# 3. Sunset — scheduled removal date announced
# 4. Removed — endpoint/field no longer works

# FastAPI deprecation implementation:
# Mark endpoints as deprecated in OpenAPI docs:
@app.get("/old-endpoint/", deprecated=True)
async def old_endpoint():
    """This endpoint is deprecated. Use /new-endpoint/ instead."""
    ...

# Add deprecation warnings in response headers:
@app.middleware("http")
async def deprecation_middleware(request: Request, call_next):
    response = await call_next(request)
    
    # Check if the deprecated endpoint was called
    if request.url.path == "/old-endpoint/":
        response.headers["Warning"] = (
            '299 - "This endpoint is deprecated. '
            'Use /new-endpoint/ instead. '
            'Removal date: 2025-06-01"'
        )
        response.headers["Sunset"] = "2025-06-01T00:00:00Z"
        response.headers["Link"] = (
            '</new-endpoint/>; rel="alternate"'
        )
    
    return response

# Sunset header (RFC 8594): tells clients when the resource
# will be removed. Clients can proactively migrate.

# Link header with rel="alternate": points to the replacement endpoint.

# Deprecation tracking — monitor usage of deprecated endpoints:
@app.middleware("http")
async def deprecation_tracking(request: Request, call_next):
    response = await call_next(request)
    
    # Track deprecated endpoint usage
    if request.url.path in DEPRECATED_ENDPOINTS:
        logger.warning(
            f"Deprecated endpoint called: {request.url.path} "
            f"from {request.client.host}"
        )
        # Send to analytics for client tracking
        track_deprecated_usage(request.url.path, request.headers.get("User-Agent"))
    
    return response

# Deprecation timeline example:
# Day 0: Announce deprecation in changelog, docs, email to clients
# Day 30: Add Warning header to responses, mark as deprecated in OpenAPI
# Day 60: Send direct email to clients still using the endpoint
# Day 90: Sunset header with removal date (90 days out)
# Day 180: Remove the endpoint (return 410 Gone)
# The key: give clients at least 6 months to migrate.
# Communicate through multiple channels (docs, email, headers).
# Track usage to know when it's safe to remove.
```

### Version routing — one codebase, multiple versions

```python
# Don't duplicate code for each version. Share the business logic,
# only differ in the request/response transformation.

# Shared business logic:
async def create_user_core(name: str, email: str, phone: str | None = None):
    """Core business logic — version-agnostic"""
    user = await db.create_user(name=name, email=email, phone=phone)
    await send_welcome_email(user.email)
    return user

# v1 adapter:
@app.post("/api/v1/users/", response_model=UserV1)
async def create_user_v1(user: UserCreateV1):
    """v1 endpoint — adapts v1 request to core logic"""
    # v1 doesn't have phone — pass None
    core_user = await create_user_core(
        name=user.name,
        email=user.email,
        phone=None,
    )
    # Adapt core response to v1 format
    return UserV1(
        id=core_user.id,
        name=core_user.name,
        email=core_user.email,
        # v1 doesn't return phone or created_at
    )

# v2 adapter:
@app.post("/api/v2/users/", response_model=UserV2)
async def create_user_v2(user: UserCreateV2):
    """v2 endpoint — adapts v2 request to core logic"""
    core_user = await create_user_core(
        name=user.name,
        email=user.email,
        phone=user.phone,  # v2 has phone
    )
    return UserV2(
        id=core_user.id,
        name=core_user.name,
        email=core_user.email,
        phone=core_user.phone,
        created_at=core_user.created_at.isoformat(),
    )

# The pattern: shared core logic, version-specific adapters.
# When adding v3, you write a new adapter, not new core logic.
# This prevents code duplication and ensures all versions
# have the same business logic (just different interfaces).

# For database models: use a single database schema.
# Different API versions transform the same database data
# into different response shapes. Don't maintain separate
# database schemas per version — that's a maintenance nightmare.
```

### Version-specific validation and error responses

```python
# Different API versions may have different validation rules
# and error response formats.

# v1 validation (lenient):
class UserCreateV1(BaseModel):
    name: str = Field(..., min_length=1)
    email: str  # No email validation in v1 (legacy)

# v2 validation (strict):
class UserCreateV2(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    email: EmailStr  # Proper email validation
    phone: str | None = Field(None, pattern=r"^\+?\d{10,15}$")

# v1 error response:
# {"detail": "Validation error"}

# v2 error response (structured):
# {"error": "validation", "details": [...]}

# FastAPI handles this automatically through different
# Pydantic models per version. The validation runs on the
# version-specific model, and the error response format
# is determined by the exception handler for that version.

# For version-specific exception handlers:
async def v1_exception_handler(request: Request, exc: Exception):
    # v1 returns simple error format
    return JSONResponse(
        status_code=400,
        content={"detail": str(exc)},
    )

async def v2_exception_handler(request: Request, exc: Exception):
    # v2 returns structured error format
    return JSONResponse(
        status_code=400,
        content={
            "error": "validation",
            "message": str(exc),
            "version": "v2",
        },
    )

# Register based on version (via middleware or router-level):
# v1_router.add_exception_handler(Exception, v1_exception_handler)
# v2_router.add_exception_handler(Exception, v2_exception_handler)
```

### API version discovery — helping clients find the right version

```python
# Clients need to know what versions are available and which
# features each version supports.

@app.get("/api/", response_model=ApiDiscovery)
async def api_discovery():
    """API discovery endpoint — lists available versions"""
    return ApiDiscovery(
        versions=[
            ApiVersion(
                version="v1",
                url="/api/v1/",
                status="deprecated",  # or "stable", "beta", "deprecated"
                sunset_date="2025-06-01",
                changelog="/changelog/v1",
            ),
            ApiVersion(
                version="v2",
                url="/api/v2/",
                status="stable",
                sunset_date=None,
                changelog="/changelog/v2",
            ),
            ApiVersion(
                version="v3",
                url="/api/v3/",
                status="beta",
                sunset_date=None,
                changelog="/changelog/v3",
            ),
        ],
        latest_version="v3",
    )

# Per-version feature discovery:
@app.get("/api/v2/features/", response_model=FeatureList)
async def v2_features():
    """List features available in v2"""
    return FeatureList(
        features=[
            Feature(name="user_management", status="stable"),
            Feature(name="phone_numbers", status="stable"),
            Feature(name="webhooks", status="beta"),
            Feature(name="analytics", status="unavailable"),  # Only in v3
        ]
    )

# OpenAPI docs per version:
# FastAPI generates separate OpenAPI specs for each version
# if you use separate routers with different tags.
# /docs for v1, /docs-v2 for v2, etc.
# Or use a single OpenAPI spec with version tags.
```

## Common mistakes / gotchas

- **Versioning too early** — don't version your API before you have external clients. Internal APIs can evolve without versioning. Add versioning when you have clients that can't be updated atomically.
- **Supporting too many versions** — each version is a maintenance burden. Support at most 2 versions at once (current + previous). Deprecate and remove old versions with a clear timeline.
- **Not documenting breaking changes** — every version change should have a changelog listing breaking changes, new features, and migration steps. Without it, clients can't migrate.
- **Breaking changes in "patch" versions** — semantic versioning: MAJOR.MINOR.PATCH. Breaking changes must be in a new MAJOR version. Never break backward compatibility in a MINOR or PATCH release. Clients expect PATCH to be safe.
- **Database schema per version** — don't maintain separate database tables per API version. Use a single database schema and transform data in the API layer. Multiple database schemas are a maintenance nightmare.
- **Forgetting to update OpenAPI docs** — each version should have its own OpenAPI spec. If you only document the latest version, clients on old versions can't find accurate documentation.
- **No deprecation monitoring** — if you deprecate an endpoint but don't track its usage, you don't know when it's safe to remove. Track deprecated endpoint usage and communicate with clients still using them.
- **Inconsistent versioning strategy** — don't mix URL versioning for some endpoints and header versioning for others. Pick one strategy and apply it consistently across the entire API.

## Practice

> [!question]- Q1. You have a FastAPI API at /api/users/ with v1. You need to add a phone number field. The field is required for new users but old clients don't send it. Design the versioning strategy and migration path.
**Answer:** This is a breaking change (adding a required field breaks old clients that don't send it). Strategy: (1) Create v2 at /api/v2/users/ with the new required phone field. (2) Keep v1 at /api/v1/users/ unchanged (phone is optional/absent). (3) In v2, if phone is missing, return 422 (validation error). (4) In v1, if phone is present, ignore it (backward-compatible). (5) Database: add phone column (nullable). v1 doesn't write it. v2 requires it. (6) Deprecation: announce v1 deprecation with 6-month timeline. Add Warning header to v1 responses. (7) Migration guide: document how to upgrade from v1 to v2 (add phone field, change URL). (8) Monitoring: track v1 usage. When v1 usage drops below 1%, remove v1. The key: v1 continues to work for existing clients. New clients use v2. Old clients migrate on their own timeline. The database supports both (nullable phone). This is the standard backward-compatible evolution pattern.

> [!question]- Q2. A client on v1 of your API complains that after your "minor update" (v1.1 → v1.2), their integration broke. You changed a string field to an integer field. Diagnose what went wrong and how to prevent it.
**Answer:** The issue: you made a breaking change in a minor version update. Semantic versioning: MAJOR.MINOR.PATCH. Breaking changes must increment the MAJOR version. Clients expect MINOR updates to be backward-compatible (new features, no breaking changes). By changing a string to an integer in v1.2, you broke clients that were sending strings. The fix: (1) Immediately revert the change in v1.2. (2) Create v2 with the integer field. (3) Keep v1 with the string field. (4) Apologize to affected clients. (5) Add automated tests that verify backward compatibility — run the v1 test suite against the v1 code to ensure no breaking changes. (6) Add a CI/CD gate that runs compatibility tests before releasing a minor version. (7) Document the semantic versioning policy clearly. Prevention: (1) Semantic versioning policy — breaking changes = new MAJOR version. (2) Automated backward compatibility tests — the v1 test suite must pass on any v1.x release. (3) API contract testing — use OpenAPI schema to verify no breaking changes in minor versions. (4) Code review checklist — explicitly check for breaking changes in minor/patch releases. (5) Deprecation process — if you need to change a field, deprecate it in v1 (mark as deprecated, add new field), then remove in v2. The key: minor versions must be backward-compatible. Breaking changes require a new major version with a migration path.

> [!question]- Q3. Compare URL path versioning, header versioning, and content negotiation for a public FastAPI API that will have mobile app clients, web clients, and third-party integrators. Which do you choose and why?
**Answer:** For a public API with diverse clients (mobile, web, third-party), choose URL path versioning. Reasons: (1) **Mobile apps** — mobile apps are hard to update (users don't update immediately). URL versioning lets you serve v1 to old app versions and v2 to new versions simultaneously. The URL is explicit — no need to parse headers. (2) **Web clients** — web apps can update quickly but may have cached API responses. URL versioning ensures cache separation (v1 and v2 have different URLs, different cache keys). (3) **Third-party integrators** — external developers need clear, explicit versioning. URL versioning is the most visible and easiest to understand. They can see the version in the URL, logs, and documentation. (4) **Debugging** — when something goes wrong, the version is visible in the URL, server logs, and error reports. With header versioning, you have to dig through headers to find the version. (5) **CDN caching** — different URLs = different cache entries. With header versioning, the same URL returns different content based on headers, which breaks CDN caching. (6) **Documentation** — each version has its own URL, making it easy to document and test. Header versioning requires documenting the header format, which is less intuitive. The trade-off: URL versioning means URLs change between versions. But for a public API, the benefits (explicit, cacheable, debuggable, mobile-friendly) far outweigh this cost. Header versioning is better for internal APIs where you control all clients and can update them atomically.

> [!question]- Q4. Your FastAPI API has 3 versions (v1, v2, v3). v1 is deprecated but 15% of traffic still uses it. You want to remove v1 but can't break those clients. Design the migration strategy.
**Answer:** Strategy: (1) **Intensify communication** — send direct emails to all clients still using v1 (track via API keys or user accounts). Include their usage statistics and a migration deadline. (2) **Add Sunset header** — include Sunset: <date> header in all v1 responses, giving a firm removal date (3 months out). (3) **Add migration proxy** — create a middleware that intercepts v1 requests, logs them, and automatically transforms them to v2 calls internally. Return v1-formatted responses to the client. This way, clients don't need to change their code — the API layer handles the transformation. (4) **Offer migration support** — provide a migration guide, sandbox environment, and dedicated support channel for clients migrating from v1. (5) **Incentivize migration** — offer benefits for migrating (higher rate limits, new features, discounted pricing). (6) **Gradual shutdown** — after the sunset date, return 410 Gone for v1 requests but include a detailed error message with migration instructions and a temporary fallback URL. (7) **Fallback period** — keep a minimal v1 compatibility layer for 3 more months (returning 410 with migration info) for clients who missed the deadline. (8) **Final removal** — after 6 months total, completely remove v1. The key: give clients multiple opportunities to migrate, make migration easy (proxy/transform), and provide a clear timeline with firm deadlines. The migration proxy is the safety net — it lets you remove v1 code while still serving v1 clients through transformation.

> [!question]- Q5. Design a backward-compatible evolution strategy for a FastAPI API endpoint that currently returns `{"id": 1, "name": "Alice"}` and needs to evolve to return `{"id": 1, "first_name": "Alice", "last_name": "", "full_name": "Alice"}` over 3 versions.
**Answer:** Evolution over 3 versions, each backward-compatible:
- **Current (v1)**: `{"id": 1, "name": "Alice"}` — single name field
- **v1.1 (backward-compatible add)**: `{"id": 1, "name": "Alice", "full_name": "Alice"}` — add full_name as alias of name. Old clients ignore full_name. New clients can use full_name.
- **v2 (backward-compatible split)**: `{"id": 1, "name": "Alice", "first_name": "Alice", "last_name": "", "full_name": "Alice"}` — add first_name and last_name. name is still present (deprecated). Old clients use name. New clients use first_name/last_name. full_name is computed from first + last.
- **v2.1 (deprecation)**: `{"id": 1, "first_name": "Alice", "last_name": "", "full_name": "Alice"}` — mark name as deprecated in OpenAPI docs. Add Warning header when name is requested. name still works but is deprecated.
- **v3 (removal)**: `{"id": 1, "first_name": "Alice", "last_name": "", "full_name": "Alice"}` — remove name field entirely. This is a breaking change — new major version. Clients using name must migrate to first_name/last_name. The key: each intermediate version is backward-compatible. Old clients continue to work. New clients can use new fields. The breaking change (removing name) only happens in v3, with a clear deprecation path and migration timeline. At each step, the database stores first_name and last_name separately. The name field is computed for backward compatibility. In v3, the computation is removed.

## Related
[[routing-and-params]]
[[pydantic-models-and-validation]]
[[error-handling-and-exception-handlers]]
[[cors-and-security-headers]]
[[system-design-for-apis-at-scale]]

#status/new