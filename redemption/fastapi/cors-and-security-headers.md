# CORS and Security Headers

## What it is
CORS (Cross-Origin Resource Sharing) controls which web origins (domains) can access your API from a browser. Security headers add extra layers of protection against common web attacks (XSS, clickjacking, MIME sniffing, protocol downgrade). This file covers CORS mechanics (simple vs preflight requests, credentials, wildcards), security headers (CSP, HSTS, X-Frame-Options, etc.), the interaction between CORS and authentication, and the common misconfigurations that either break your API or leave it vulnerable.

## Why it matters
CORS is the #1 cause of "my API works locally but fails in production" errors. Security headers are the difference between an API that's protected against common attacks and one that's an easy target. In interviews, security questions test whether you understand CORS, security headers, and common web vulnerabilities. For your work — any API accessed from a browser — CORS and security headers are non-negotiable. Getting CORS wrong breaks your frontend. Getting security headers wrong exposes your users to attacks.

## Core example

### CORS — the mechanics

```python
# CORS exists because of the Same-Origin Policy (SOP) in browsers.
# SOP: a web page can only make requests to the same origin
# (protocol + host + port) as the page itself.
# 
# CORS is the mechanism that relaxes SOP for specific origins.
# Without CORS, your frontend at https://myapp.com can't call
# your API at https://api.myapp.com (different subdomain = different origin).

# Simple request (no preflight):
# A request is "simple" if ALL of these are true:
# - Method is GET, POST, or HEAD
# - Content-Type is application/x-www-form-urlencoded,
#   multipart/form-data, or text/plain
# - No custom headers (only Accept, Accept-Language, Content-Language,
#   Content-Type, and a few others)
# 
# For simple requests, the browser sends the request directly
# and checks the Access-Control-Allow-Origin header in the response.
# If the origin is allowed, the response is available to JavaScript.
# If not, the browser blocks it.

# Preflight request (OPTIONS):
# A request is NOT simple if:
# - Method is PUT, DELETE, PATCH, etc.
# - Content-Type is application/json
# - Custom headers (Authorization, X-API-Key, etc.)
# 
# For non-simple requests, the browser FIRST sends an OPTIONS
# request (preflight) to check if the actual request is allowed.
# The server responds with CORS headers indicating what's allowed.
# If the preflight succeeds, the browser sends the actual request.
# If the preflight fails, the actual request is never sent.

# This is why your POST /users/ with JSON body and Authorization
# header triggers an OPTIONS request before the actual POST.
# If the server doesn't respond correctly to OPTIONS, the POST
# never happens.
```

### FastAPI CORS middleware — correct configuration

```python
from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI

app = FastAPI()

# CORRECT production configuration:
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://myapp.com",
        "https://www.myapp.com",
        "https://admin.myapp.com",
    ],
    allow_credentials=True,  # Allow cookies/auth headers
    allow_methods=[
        "GET",
        "POST",
        "PUT",
        "DELETE",
        "OPTIONS",  # Required for preflight
        "PATCH",
    ],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "X-API-Key",
        "X-Requested-With",
        "Accept",
        "Origin",
    ],
    max_age=3600,  # Cache preflight for 1 hour (reduces OPTIONS requests)
)

# CRITICAL: allow_origins=["*"] with allow_credentials=True is
# REJECTED by browsers. If you need credentials (cookies, auth headers),
# you MUST specify exact origins — wildcards are not allowed.
# 
# If you DON'T need credentials, you can use:
# allow_origins=["*"]  # Allow all origins (for public APIs)
# allow_credentials=False  # Default
# 
# But for authenticated APIs, always specify exact origins.

# Development configuration (allow all):
if settings.debug:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Allow all for development
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# But note: even in development, if you're testing auth/cookies,
# you need exact origins. Wildcards don't work with credentials.
```

### CORS gotchas — the common mistakes

```python
# Gotcha 1: Wildcard with credentials
# This is the #1 CORS error.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # WRONG with credentials
    allow_credentials=True,  # WRONG with wildcard
)
# Browsers reject this combination. The request fails silently
# (browser blocks it, no error in FastAPI logs).
# Fix: specify exact origins when using credentials.

# Gotcha 2: Missing OPTIONS handling
# FastAPI's CORSMiddleware handles OPTIONS automatically.
# But if you define your own OPTIONS route, it conflicts.
# DON'T do this:
@app.options("/users/")  # Don't define OPTIONS routes manually
async def options_handler():
    ...
# The CORSMiddleware already handles OPTIONS. Your handler
# won't be called, or it will conflict.

# Gotcha 3: Dynamic origins without validation
# If you need to allow dynamic origins (e.g., subdomains for
# multi-tenant apps), validate them — don't just echo back
# whatever Origin header is sent.

ALLOWED_DOMAINS = {"myapp.com", "staging.myapp.com"}

def is_allowed_origin(origin: str) -> bool:
    """Validate origin against allowed domains"""
    if not origin:
        return False
    try:
        parsed = urlparse(origin)
        hostname = parsed.hostname
        # Allow subdomains of allowed domains
        return any(
            hostname == domain or hostname.endswith(f".{domain}")
            for domain in ALLOWED_DOMAINS
        )
    except:
        return False

# Custom CORS middleware with dynamic origin validation:
@app.middleware("http")
async def dynamic_cors(request: Request, call_next):
    origin = request.headers.get("Origin")
    
    response = await call_next(request)
    
    if origin and is_allowed_origin(origin):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
    
    # Handle preflight
    if request.method == "OPTIONS":
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS, PATCH"
        response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type, X-API-Key"
        response.headers["Access-Control-Max-Age"] = "3600"
    
    return response

# Gotcha 4: Not including the Vary header
# When using dynamic origins (not wildcard), the response varies
# based on the Origin header. Add Vary: Origin so that CDNs and
# proxies cache different versions for different origins.
# FastAPI's CORSMiddleware adds this automatically when using
# specific origins (not wildcard).

# Gotcha 5: CORS is a browser-only protection
# CORS only protects against browser-based attacks. It does NOT
# prevent attackers from calling your API directly (curl, Postman,
# scripts). CORS is not authentication or authorization. It's a
# browser policy. Your API must still authenticate and authorize
# every request regardless of CORS.
```

### Security headers — the essential set

```python
# Security headers add defense-in-depth. They protect against
# common web attacks that CORS alone doesn't cover.

# Middleware to add security headers:
@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    
    # 1. Content-Security-Policy (CSP)
    # Controls which resources (scripts, styles, images, etc.)
    # can be loaded. Prevents XSS attacks.
    # For APIs, a minimal CSP is fine:
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; "  # Block everything by default
        "frame-ancestors 'none'; "  # Prevent clickjacking
        "base-uri 'self'; "  # Prevent base tag injection
    )
    # If your API serves HTML (docs, dashboard), you need a
    # more permissive CSP with specific script/style sources.
    # For pure JSON APIs, the above is sufficient.

    # 2. Strict-Transport-Security (HSTS)
    # Forces browsers to use HTTPS for future requests.
    # Prevents SSL stripping attacks.
    # Only set this if you're sure HTTPS is always available.
    response.headers["Strict-Transport-Security"] = (
        "max-age=31536000; "  # 1 year
        "includeSubDomains; "  # Apply to all subdomains
        "preload "  # Submit to HSTS preload list
    )

    # 3. X-Content-Type-Options
    # Prevents MIME type sniffing. Forces the browser to use
    # the Content-Type header as-is.
    response.headers["X-Content-Type-Options"] = "nosniff"

    # 4. X-Frame-Options
    # Prevents clickjacking — your API response can't be embedded
    # in an iframe on another site.
    response.headers["X-Frame-Options"] = "DENY"
    # Or: "SAMEORIGIN" — allow embedding on same origin only
    # Note: frame-ancestors in CSP is the modern replacement,
    # but X-Frame-Options is still needed for older browsers.

    # 5. X-XSS-Protection
    # Legacy XSS filter. Deprecated but still included for
    # older browsers.
    response.headers["X-XSS-Protection"] = "1; mode=block"

    # 6. Referrer-Policy
    # Controls how much referrer information is sent with requests.
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    # Send full URL for same-origin, origin only for cross-origin,
    # nothing for HTTPS→HTTP downgrades.

    # 7. Permissions-Policy (formerly Feature-Policy)
    # Controls which browser features (camera, microphone, geolocation)
    # can be used. For APIs, disable everything.
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=(), usb=()"
    )

    # 8. Cache-Control for sensitive endpoints
    # Prevent caching of sensitive API responses
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = (
            "no-store, "  # Don't cache anywhere
            "max-age=0, "  # Already expired
            "must-revalidate"  # Always revalidate
        )
        response.headers["Pragma"] = "no-cache"  # HTTP/1.0 compatibility
    
    return response

# Note: security headers are most important for HTML responses.
# For JSON APIs, the most critical ones are:
# - Content-Security-Policy (frame-ancestors)
# - X-Content-Type-Options (nosniff)
# - X-Frame-Options (DENY)
# - Cache-Control (no-store for sensitive data)
# The rest are mainly for HTML pages.
```

### CORS + Auth — the secure combination

```python
# When using JWT/auth with CORS, the order matters.
# Preflight (OPTIONS) requests should NOT require authentication.
# Otherwise, the browser can't send the preflight (it doesn't
# include auth headers on preflight), and the actual request
# never happens.

# Correct order: CORS first, then auth
app.add_middleware(CORSMiddleware, ...)  # First added = outermost

# Then auth middleware (or dependency)
@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    # Check auth AFTER CORS has handled the preflight
    # If it's a preflight (OPTIONS), skip auth
    if request.method == "OPTIONS":
        return await call_next(request)
    
    # Check auth for actual requests
    token = request.headers.get("Authorization")
    if not token or not valid_token(token):
        raise HTTPException(401, "Unauthorized")
    
    return await call_next(request)

# FastAPI's CORSMiddleware handles OPTIONS automatically and
# returns a 200 response before your auth middleware runs.
# So preflight requests never reach your auth check. This is correct.

# But if you implement auth as a dependency on specific routes:
@app.get("/protected/", dependencies=[Depends(get_current_user)])
async def protected():
    ...

# The preflight (OPTIONS) to /protected/ is handled by CORSMiddleware
# and returns 200 without calling the endpoint or the dependency.
# The actual GET /protected/ requires auth. This is correct.

# Credentials and CORS:
# If you use cookies for authentication (session cookies, httpOnly cookies),
# you need:
# 1. allow_credentials=True in CORS config
# 2. Exact origins (not wildcard)
# 3. WithCredentials: true in the frontend (fetch/axios)
# 
# Frontend (fetch):
# fetch("https://api.myapp.com/users/", {
#   credentials: "include"  # Send cookies with cross-origin requests
# })
# 
# Without credentials: "include", cookies aren't sent with
# cross-origin requests, even if the server allows them.
# 
# For JWT in Authorization header, you don't need credentials: "include".
# The header is sent automatically with the request.
# But you still need CORS to allow the origin.
```

### CORS testing — verifying your configuration

```python
# Test CORS configuration to verify it's correct:

# Test 1: Simple GET with origin
# curl -H "Origin: https://myapp.com" -I https://api.myapp.com/users/
# Should return:
# Access-Control-Allow-Origin: https://myapp.com
# Access-Control-Allow-Credentials: true (if enabled)
# Vary: Origin

# Test 2: Preflight (OPTIONS) request
# curl -X OPTIONS \
#   -H "Origin: https://myapp.com" \
#   -H "Access-Control-Request-Method: POST" \
#   -H "Access-Control-Request-Headers: Authorization, Content-Type" \
#   -I https://api.myapp.com/users/
# Should return:
# Access-Control-Allow-Origin: https://myapp.com
# Access-Control-Allow-Methods: GET, POST, PUT, DELETE, OPTIONS, PATCH
# Access-Control-Allow-Headers: Authorization, Content-Type
# Access-Control-Max-Age: 3600

# Test 3: Disallowed origin
# curl -H "Origin: https://evil.com" -I https://api.myapp.com/users/
# Should NOT return Access-Control-Allow-Origin: https://evil.com
# Or should not include CORS headers at all

# Test 4: Credentials with wildcard (should fail)
# If allow_origins=["*"] and allow_credentials=True,
# the browser will reject the response. Test in DevTools:
# Access to fetch at '...' from origin '...' has been blocked
# by CORS policy: The 'Access-Control-Allow-Credentials' header
# must not be 'true' when 'Access-Control-Allow-Origin' is '*'.

# Test 5: Security headers
# curl -I https://api.myapp.com/users/
# Should return all configured security headers:
# Content-Security-Policy, X-Frame-Options, X-Content-Type-Options,
# Strict-Transport-Security, etc.

# Automated test (pytest + TestClient):
def test_cors_allowed_origin():
    response = client.get(
        "/",
        headers={"Origin": "https://myapp.com"},
    )
    assert response.headers["access-control-allow-origin"] == "https://myapp.com"

def test_cors_disallowed_origin():
    response = client.get(
        "/",
        headers={"Origin": "https://evil.com"},
    )
    # Should not allow evil.com
    assert response.headers.get("access-control-allow-origin") != "https://evil.com"

def test_preflight():
    response = client.options(
        "/users/",
        headers={
            "Origin": "https://myapp.com",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization, Content-Type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-methods"] == "POST, GET, OPTIONS"
    assert response.headers["access-control-allow-headers"] == "Authorization, Content-Type"

def test_security_headers():
    response = client.get("/")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert "content-security-policy" in response.headers
```

## Common mistakes / gotchas

- **Wildcard with credentials** — the #1 CORS mistake. `allow_origins=["*"]` with `allow_credentials=True` is rejected by browsers. Always use exact origins when credentials are needed.
- **Not allowing the correct methods** — if your frontend uses PUT or DELETE but CORS only allows GET and POST, the preflight fails. Always include all HTTP methods your API uses.
- **Not allowing custom headers** — if your frontend sends `X-API-Key` or `Authorization` but CORS doesn't allow them in `allow_headers`, the preflight fails. Always include all custom headers.
- **Security headers on all responses** — some security headers (CSP, HSTS) are meant for HTML responses, not JSON APIs. For JSON APIs, use a minimal set (nosniff, frame-ancestors, cache-control). Over-configuring can break API clients.
- **CORS as a security measure** — CORS is not security. It's a browser policy. An attacker can still call your API with curl. Always authenticate and authorize every request regardless of CORS.
- **HSTS without HTTPS** — if you set HSTS but your site doesn't support HTTPS, browsers will refuse to connect over HTTP and can't reach HTTPS either. Only set HSTS when HTTPS is guaranteed.
- **CSP too restrictive** — if your API serves HTML (docs, dashboard) and your CSP blocks all scripts, the page won't work. Test CSP in report-only mode first: `Content-Security-Policy-Report-Only` with a report-uri to collect violations before enforcing.
- **Forgetting Vary: Origin** — when using specific origins (not wildcard), responses vary by Origin. Without Vary: Origin, CDNs and proxies may cache the wrong version. FastAPI adds this automatically, but if you implement custom CORS, don't forget it.

## Practice

> [!question]- Q1. A FastAPI API is deployed at https://api.myapp.com. The frontend is at https://myapp.com and https://admin.myapp.com. The API uses JWT in the Authorization header. Design the CORS and security header configuration.
**Answer:** CORS configuration: allow_origins=["https://myapp.com", "https://admin.myapp.com"], allow_credentials=False (JWT in header doesn't need credentials), allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"], allow_headers=["Authorization", "Content-Type", "X-API-Key", "Accept"], max_age=3600. Security headers: Content-Security-Policy "default-src 'none'; frame-ancestors 'none'", X-Content-Type-Options "nosniff", X-Frame-Options "DENY", Referrer-Policy "strict-origin-when-cross-origin", Permissions-Policy "camera=(), microphone=(), geolocation=()". For production: add Strict-Transport-Security with max-age=31536000 and includeSubdomains. Cache-Control for API endpoints: no-store, max-age=0, must-revalidate. The design: two specific origins (no wildcard, even though credentials aren't used — best practice), JWT in Authorization header (no cookie credentials needed), minimal CSP for JSON API, nosniff to prevent MIME sniffing, frame-ancestors to prevent clickjacking. The preflight (OPTIONS) is handled by CORSMiddleware. Auth is checked on actual requests. No conflict.

> [!question]- Q2. Your FastAPI API works locally (frontend on localhost:3000, API on localhost:8000) but in production, the browser blocks all API requests with a CORS error. The API is at https://api.myapp.com and frontend at https://myapp.com. Diagnose and fix.
**Answer:** The issue is CORS. Locally, both are on localhost but different ports (3000 vs 8000) — different origins, but browsers may handle localhost more leniently, or your local CORS config allows all origins. In production, the browser enforces SOP strictly. Diagnosis: check the browser DevTools → Network tab → the failed request. The error message tells you exactly what's missing: "No 'Access-Control-Allow-Origin' header" (CORS not configured), "Origin https://myapp.com is not allowed" (origin not in allow_origins list), or "Cannot allow credentials with wildcard" (wildcard with credentials). Fix: add CORS middleware with allow_origins=["https://myapp.com"] (exact origin). If using Authorization header, add allow_headers=["Authorization", "Content-Type"]. If using POST/PUT/DELETE, add allow_methods for those. Ensure the CORSMiddleware is added before auth middleware (so OPTIONS preflight is handled before auth check). Also check: if the frontend makes requests with credentials (cookies), set allow_credentials=True and ensure no wildcard origin. Test with curl to verify the CORS headers are present. The key: the browser blocks the response because the server didn't send the correct CORS headers. Add the CORSMiddleware with the correct production origin.

> [!question]- Q3. Explain the difference between CORS and CSRF. Do you need both protections for a FastAPI API that uses JWT authentication?
**Answer:** CORS (Cross-Origin Resource Sharing): a browser mechanism that controls which origins can make requests to your API. It's enforced by the browser — the browser checks the Access-Control-Allow-Origin header and blocks the response if the origin isn't allowed. CSRF (Cross-Site Request Forgery): an attack where a malicious site tricks a user's browser into making an authenticated request to your API. The user is logged in (cookies sent automatically), and the malicious site submits a form or makes a request that the browser sends with the user's cookies. Protection: SameSite cookies, CSRF tokens, checking Origin/Referer headers. For JWT authentication: if you store JWT in localStorage and send it via Authorization header, CSRF is NOT a risk (cookies aren't involved, the malicious site can't read localStorage to get the token). CORS is still needed (browser SOP). If you store JWT in httpOnly cookies, CSRF IS a risk (cookies are sent automatically with cross-origin requests). You need both CORS (for SOP) and CSRF protection (SameSite cookies or CSRF token). Recommendation: use Authorization header with JWT (not cookies) to avoid CSRF. Then you only need CORS. If you must use cookies (for SSR, third-party cookies), add SameSite=Strict or Lax on cookies, and validate Origin header on state-changing requests. The key: JWT in header → no CSRF risk, need CORS. JWT in cookies → CSRF risk, need both CORS and CSRF protection.

> [!question]- Q4. A FastAPI API needs to support file uploads from a frontend at a different origin. The upload uses multipart/form-data with an Authorization header. The file can be up to 100MB. Design the CORS configuration and any additional considerations.
**Answer:** CORS configuration: allow_origins=["https://myapp.com"] (exact origin), allow_credentials=True if using cookies, allow_methods=["POST", "PUT", "OPTIONS"], allow_headers=["Authorization", "Content-Type"]. Since multipart/form-data with Authorization header is not a simple request, it triggers a preflight (OPTIONS). The preflight must succeed before the file upload is sent. Additional considerations: (1) **Max request size** — configure uvicorn/nginx to allow large requests: uvicorn --limit-concurrency and client_max_body_size 100M in nginx. (2) **Upload timeout** — large file uploads take time. Increase proxy_read_timeout and uvicorn --timeout to 300s or higher. (3) **Streaming upload** — don't buffer the entire file in memory. Use UploadFile (which uses SpooledTemporaryFile) to stream to disk. (4) **CORS max_age** — set max_age=3600 to cache the preflight for 1 hour. This avoids a preflight for every file upload. (5) **Progress tracking** — for large uploads, consider a separate progress endpoint or WebSocket for upload progress. (6) **Security** — validate file type, size, and content. Don't trust the Content-Type header. Scan for malware. Store in S3, not local disk. (7) **Rate limiting** — file uploads consume bandwidth and storage. Rate limit by user tier. (8) **CORS for upload-specific endpoint** — if you have a dedicated upload endpoint, you can apply more restrictive CORS just for that endpoint (using middleware or route-specific CORS). The key: large file uploads with auth headers trigger preflight. Cache the preflight. Configure server limits for large requests. Stream to disk. Validate and secure uploads.

> [!question]- Q5. Your FastAPI API serves both a web dashboard (HTML) and a JSON API. The web dashboard needs inline scripts and styles for charts. The JSON API should have strict security headers. Design the security header strategy.
**Answer:** Two different security policies for two different response types. Strategy: (1) **Middleware that checks response type** — add security headers based on the Content-Type or the request path. (2) **JSON API responses** (application/json): strict CSP "default-src 'none'; frame-ancestors 'none'", X-Content-Type-Options "nosniff", X-Frame-Options "DENY", Cache-Control "no-store". No inline scripts needed for JSON. (3) **HTML dashboard responses** (text/html): CSP that allows the necessary resources: "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data: https:; connect-src 'self' https://api.myapp.com; frame-ancestors 'self'". This allows CDN scripts/styles for charts, inline scripts for chart initialization, and data: URLs for chart images. (4) **Implementation**: in the security headers middleware, check response.headers.get("content-type") or request.url.path. If it starts with /api/ or is JSON, use strict CSP. If it's HTML (dashboard, docs), use permissive CSP. (5) **Alternative**: serve the dashboard from a different subdomain (app.myapp.com) with its own CORS and security policy. The API (api.myapp.com) has strict JSON-only policy. The dashboard (app.myapp.com) has HTML-appropriate policy. This is cleaner — separation by subdomain. (6) **CSP reporting**: for the dashboard CSP, add report-uri /csp-report to collect CSP violations. Monitor and tighten the CSP over time. Start with report-only mode (Content-Security-Policy-Report-Only) to collect violations before enforcing. The key: JSON APIs need minimal security headers. HTML dashboards need permissive CSP for functionality. Separate by content type or subdomain. Always include frame-ancestors and nosniff for both.

## Related
[[middleware]]
[[auth-oauth2-jwt]]
[[request-response-lifecycle]]
[[system-design-for-apis-at-scale]]
[[error-handling-and-exception-handlers]]

#status/new