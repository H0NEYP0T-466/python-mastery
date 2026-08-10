# Auth — OAuth2 JWT

## What it is
FastAPI's built-in OAuth2 password flow with JWT tokens is the standard pattern for API authentication. The client sends username/password to a token endpoint, receives a JWT (signed token), and includes it in subsequent requests as a `Bearer` token. FastAPI verifies the signature and extracts the token payload. This file covers the full flow: token issuance, token verification, token refresh, scopes/roles, token revocation patterns, and the security considerations that separate production auth from tutorial auth.

## Why it matters
Auth is the most security-critical part of any API. A mistake here means anyone can access your data. In interviews, auth questions test whether you understand JWT structure, signing algorithms, token storage, refresh token rotation, and the difference between authentication and identity. For your work — any API that serves user data — auth is non-negotiable. Getting it wrong is catastrophic.

## Core example

### The full OAuth2 password flow

```python
from fastapi import FastAPI, Depends, HTTPException, Security, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import jwt, JWTError
from passlib.context import CryptContext
from datetime import datetime, timedelta
from pydantic import BaseModel

app = FastAPI()

# Password hashing — bcrypt (never use plain text or MD5/SHA)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# OAuth2 scheme — tokenUrl is where clients get tokens
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")

# JWT configuration
SECRET_KEY = "your-super-secret-key-change-in-production"  # Use env var!
ALGORITHM = "HS256"  # HMAC with SHA-256
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# Models
class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    username: str | None = None

class User(BaseModel):
    username: str
    email: str | None = None
    full_name: str | None = None
    disabled: bool | None = None

class UserInDB(User):
    hashed_password: str

# Password utilities
def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

# Token creation
def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

# Token verification
async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        token_data = TokenData(username=username)
    except JWTError:
        raise credentials_exception
    
    # Look up user in database
    user = await get_user_by_username(username)
    if user is None:
        raise credentials_exception
    if user.disabled:
        raise HTTPException(status_code=400, detail="Inactive user")
    return user

# Login endpoint
@app.post("/auth/token", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    # form_data contains username and password
    user = await authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    
    return {"access_token": access_token, "token_type": "bearer"}

# Protected endpoint
@app.get("/users/me/", response_model=User)
async def read_users_me(current_user: User = Depends(get_current_user)):
    return current_user
```

### JWT structure — what's inside the token

```python
# A JWT has three parts: header.payload.signature (base64url encoded)

# Header (typical):
# {"alg": "HS256", "typ": "JWT"}

# Payload (claims):
# {
#   "sub": "alice",      # Subject (username/user ID)
#   "exp": 1736000000,   # Expiration time (Unix timestamp)
#   "iat": 1735996400,   # Issued at time
#   "nbf": 1735996400,   # Not valid before
#   "role": "user",      # Custom claim (role, permissions)
#   "user_id": 123       # Custom claim
# }

# Signature: HMAC-SHA256(base64(header) + "." + base64(payload), secret_key)

# The signature proves the token wasn't tampered with.
# Anyone can read the payload (it's base64, not encrypted).
# Only the holder of the secret key can create/modify a valid signature.

# NEVER store sensitive data (passwords, PII) in JWT payload —
# it's readable by anyone who intercepts the token.

# Common claims:
# sub: subject (user identifier)
# exp: expiration (mandatory for security)
# iat: issued at
# nbf: not valid before (future-dated token)
# iss: issuer (your API's URL)
# aud: audience (who the token is for)
# jti: JWT ID (unique identifier for revocation)
```

### Refresh tokens — the complete pattern

```python
# Access tokens are short-lived (15-30min). Refresh tokens are
# long-lived (7-30 days) and used to get new access tokens.

# The refresh token is NOT a JWT — it's a random string stored
# in the database. This allows revocation.

import secrets
from datetime import timedelta

REFRESH_TOKEN_EXPIRE_DAYS = 7

class RefreshToken(BaseModel):
    token: str  # Random string
    user_id: int
    expires_at: datetime
    revoked: bool = False

# Login with refresh token:
@app.post("/auth/token", response_model=TokenWithRefresh)
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    user = await authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(401, "Invalid credentials")
    
    access_token = create_access_token(
        data={"sub": user.username},
        expires_delta=timedelta(minutes=30)
    )
    
    # Create refresh token (random string, not JWT)
    refresh_token = secrets.token_urlsafe(32)
    await store_refresh_token(user.id, refresh_token, days=7)
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "refresh_token": refresh_token,
        "expires_in": 30 * 60,  # seconds
    }

# Refresh endpoint:
@app.post("/auth/refresh", response_model=Token)
async def refresh_token(refresh_token_data: RefreshTokenRequest):
    # Verify the refresh token exists and is valid
    token_record = await get_refresh_token(refresh_token_data.refresh_token)
    
    if not token_record or token_record.revoked:
        raise HTTPException(401, "Invalid refresh token")
    
    if token_record.expires_at < datetime.utcnow():
        raise HTTPException(401, "Refresh token expired")
    
    # Get user and create new access token
    user = await get_user_by_id(token_record.user_id)
    new_access_token = create_access_token(
        data={"sub": user.username},
        expires_delta=timedelta(minutes=30)
    )
    
    # Option 1: Rotate refresh token (recommended)
    # Invalidate old refresh token, issue new one
    await revoke_refresh_token(refresh_token_data.refresh_token)
    new_refresh_token = secrets.token_urlsafe(32)
    await store_refresh_token(user.id, new_refresh_token, days=7)
    
    return {
        "access_token": new_access_token,
        "token_type": "bearer",
        "refresh_token": new_refresh_token,  # New refresh token
    }

# Logout — revoke refresh token
@app.post("/auth/logout")
async def logout(refresh_token: str):
    await revoke_refresh_token(refresh_token)
    # The access token is still valid until expiration,
    # but the refresh token is revoked — user can't get new access tokens
    return {"message": "Logged out"}

# Why refresh tokens are random strings, not JWTs:
# 1. Revocation — you can delete the token from the DB
# 2. No signature verification needed — just a DB lookup
# 3. If a refresh token is compromised, you can revoke it
# 4. JWT access tokens can't be revoked without a blacklist
#    (which defeats the purpose of stateless JWTs)
```

### Scopes and role-based access control

```python
from fastapi import Security

# OAuth2 scopes — fine-grained permissions
# Scopes are strings like "read:users", "write:posts", "admin"

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/auth/token",
    scopes={
        "read:users": "Read user information",
        "write:users": "Create or update users",
        "read:posts": "Read posts",
        "write:posts": "Create or delete posts",
        "admin": "Full admin access",
    },
)

# Scope checking in dependencies:
async def get_current_user_with_scope(
    required_scope: str,
    token: str = Depends(oauth2_scheme),
):
    payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    scopes = payload.get("scopes", [])
    
    if required_scope not in scopes:
        raise HTTPException(
            status_code=403,
            detail=f"Insufficient scope: {required_scope}",
        )
    
    user = await get_user(payload["sub"])
    return user

# Using Security with scopes:
@app.get("/users/", dependencies=[
    Security(oauth2_scheme, scopes=["read:users"])
])
async def list_users():
    ...

@app.post("/users/", dependencies=[
    Security(oauth2_scheme, scopes=["write:users"])
])
async def create_user():
    ...

# Role-based access (simpler than scopes for simple cases):
async def require_role(required_role: str):
    def checker(token: str = Depends(oauth2_scheme)):
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        role = payload.get("role", "user")
        
        if role != required_role:
            raise HTTPException(403, "Insufficient role")
        
        return payload
    return checker

@app.get("/admin/", dependencies=[Depends(require_role("admin"))])
async def admin_panel():
    return {"message": "admin panel"}

# Scopes vs roles:
# Scopes: fine-grained, per-action permissions (read:users, write:posts)
# Roles: coarse-grained, user categories (admin, user, moderator)
# Use scopes for fine-grained API permissions.
# Use roles for simple role-based access.
# You can combine both: roles for broad access, scopes for specific actions.
```

### Token revocation — the JWT problem

```python
# JWTs are stateless — once issued, they're valid until expiration.
# There's no built-in way to revoke a JWT before it expires.

# Solutions (in order of practicality):

# 1. Short-lived access tokens + refresh tokens (recommended)
# Access tokens expire quickly (15-30min). Even if compromised,
# they're only valid for a short time. Refresh tokens are stored
# in DB and can be revoked. This is the standard approach.

# 2. Token blacklist (for immediate revocation)
# Store revoked JWT IDs (jti) in Redis with TTL = token expiry.
# On each request, check if the token's jti is in the blacklist.
# Adds a Redis lookup per request — defeats some benefits of JWT.

REDIS = redis.asyncio.from_url(REDIS_URL)

async def is_token_revoked(jti: str) -> bool:
    return await REDIS.get(f"revoked:{jti}") is not None

async def revoke_token(jti: str, expires_at: datetime):
    # Store in Redis until the token would naturally expire
    ttl = int((expires_at - datetime.utcnow()).total_seconds())
    await REDIS.setex(f"revoked:{jti}", ttl, "revoked")

# In get_current_user:
async def get_current_user(token: str = Depends(oauth2_scheme)):
    payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    jti = payload.get("jti")
    
    if jti and await is_token_revoked(jti):
        raise HTTPException(401, "Token revoked")
    
    # ... rest of verification ...

# 3. Rotate signing key (nuclear option)
# Change SECRET_KEY → all existing tokens become invalid.
# Use only for catastrophic compromise.
# Requires rotating the key in all services that verify tokens.

# 4. Token versioning
# Store a token_version in the user record. Include it in JWT payload.
# When user changes password or logs out, increment token_version.
# Old tokens (with old version) are rejected.
# This is lightweight — no Redis needed, just a DB field.

# In get_current_user:
async def get_current_user(token: str = Depends(oauth2_scheme)):
    payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    username = payload["sub"]
    token_version = payload.get("version", 1)
    
    user = await get_user_by_username(username)
    if user.token_version != token_version:
        raise HTTPException(401, "Token revoked")
    
    # ... return user ...

# On password change or logout:
await user.update(token_version=user.token_version + 1)
# All previous tokens for this user are now invalid

# Recommendation: use approach 1 (short-lived + refresh tokens)
# for most cases. Add approach 4 (token versioning) if you need
# per-user revocation without Redis. Only use approach 2 (blacklist)
# if you need immediate revocation of specific tokens.
```

### Security best practices — what tutorials skip

```python
# 1. NEVER hardcode secrets — use environment variables
import os
SECRET_KEY = os.environ.get("JWT_SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("JWT_SECRET_KEY must be set")

# 2. Use strong signing algorithms
# HS256 (HMAC-SHA256) is fine for single-service apps.
# RS256 (RSA) is for multi-service apps where verification
# is done by services that don't have the signing key.
# NEVER use "none" algorithm — it allows unsigned tokens.

# 3. Set proper token expiration
# Access tokens: 15-60 minutes (shorter = more secure)
# Refresh tokens: 7-30 days (stored securely, revocable)
# Always include exp claim in JWT

# 4. Use HTTPS in production
# JWTs in transit without HTTPS can be intercepted.
# Always use TLS in production.

# 5. Store tokens securely on the client
# NEVER store JWT in localStorage (XSS vulnerability).
# Use httpOnly cookies for web apps.
# Use secure storage (Keychain, Keystore) for mobile apps.

# 6. Include jti (JWT ID) for revocation
import uuid
def create_access_token(data: dict, ...):
    to_encode = data.copy()
    to_encode["jti"] = str(uuid.uuid4())  # Unique ID
    # ... rest ...

# 7. Validate all claims
# Don't just check the signature. Also validate:
# exp: token not expired (automatic with jose)
# nbf: token not used before time
# iss: token issued by your service
# aud: token intended for your service

# 8. Rate limit the token endpoint
# The /auth/token endpoint is a brute-force target.
# Rate limit by IP and username.
# Add CAPTCHA or delay after multiple failed attempts.

# 9. Use secure password hashing
# bcrypt, argon2, or scrypt — NOT MD5, SHA-1, or SHA-256
# bcrypt is the minimum. argon2 is the gold standard.
# passlib supports all of them.

# 10. Log authentication events
# Log successful and failed logins (without logging passwords).
# Monitor for brute-force attacks.
# Alert on unusual patterns (many failed logins from one IP).
```

## Common mistakes / gotchas

- **Hardcoding the secret key** — the #1 security mistake. The secret key must be in environment variables, committed to version control. If it's leaked, rotate it immediately.
- **Not setting token expiration** — JWTs without exp are valid forever. If intercepted, they're usable indefinitely. Always set exp.
- **Using symmetric key (HS256) across multiple services** — if multiple services need to verify tokens, they all have the signing key. If one service is compromised, all tokens can be forged. Use RS256 (asymmetric) for multi-service setups.
- **Storing sensitive data in JWT payload** — JWT payload is base64, not encrypted. Anyone who intercepts the token can read it. Never store passwords, PII, or sensitive data in JWT.
- **No refresh token rotation** — if a refresh token is stolen and not rotated, the attacker can keep getting new access tokens. Always rotate (invalidate old, issue new) on each refresh.
- **Not validating the audience claim** — if you have multiple services using the same JWT, validate the aud claim to ensure the token was issued for your service.
- **Ignoring token revocation** — JWTs can't be revoked by design. If you need revocation (logout, password change), use short-lived tokens + refresh tokens, or token versioning.
- **Using weak password hashing** — MD5, SHA-1, or even plain SHA-256 are not suitable for password hashing. They're too fast and vulnerable to brute-force. Use bcrypt (minimum) or argon2 (recommended).
- **Not rate limiting the auth endpoint** — the token endpoint is vulnerable to brute-force attacks. Rate limit by IP and username.

## Practice

> [!question]- Q1. Design an auth system for a FastAPI API that supports: (1) username/password login, (2) social login (Google OAuth2), (3) API key authentication for service-to-service calls, (4) token refresh, (5) role-based admin access. Show the token structure and endpoint design.
**Answer:**
```python
# Token structure (JWT):
# {
#   "sub": "user_123",
#   "exp": 1736000000,
#   "iat": 1735996400,
#   "jti": "uuid-v4",
#   "role": "user",  # or "admin"
#   "provider": "local"  # or "google", "api_key"
# }

# Endpoints:
# POST /auth/local/login — username/password → JWT + refresh token
# POST /auth/google/callback — Google OAuth2 code → JWT + refresh token
# POST /auth/refresh — refresh token → new JWT + new refresh token
# POST /auth/logout — revoke refresh token
# GET /admin/ — requires role="admin"

# API key auth (for service-to-service):
api_key_header = APIKeyHeader(name="X-API-Key")

async def verify_api_key(api_key: str = Security(api_key_header)):
    service = await db.get_service_by_key(api_key)
    if not service or service.disabled:
        raise HTTPException(401, "Invalid API key")
    return service

# For service endpoints:
@app.post("/internal/webhook/")
async def webhook(data: WebhookData, service: Service = Depends(verify_api_key)):
    # Service-to-service call validated via API key
    ...

# The design: user-facing auth uses JWT + refresh tokens.
# Service-to-service uses API keys (simpler, no token rotation needed).
# Social login uses OAuth2 flow — exchange authorization code for JWT.
# All auth methods produce a consistent JWT structure for downstream use.
```

> [!question]- Q2. An attacker steals a user's JWT access token. What can they do, and what can you do to minimize the damage? Compare with stealing a refresh token.
**Answer:** Stolen JWT access token: the attacker can make requests as the user until the token expires (typically 15-30min). Damage is limited by the short expiration. If you have a token blacklist or token versioning, you can revoke it. Without those, you must wait for expiration. Stolen refresh token: the attacker can generate new access tokens indefinitely until the refresh token is revoked or expires (7-30 days). This is more dangerous. Mitigation: (1) Short-lived access tokens limit the window. (2) Refresh token rotation invalidates the stolen token on next legitimate use. (3) Store refresh tokens in DB with IP/device tracking — detect anomalies (same refresh token from two different IPs). (4) Allow users to revoke all sessions (delete all refresh tokens). (5) Use httpOnly cookies for refresh tokens (prevents XSS theft). The key principle: access tokens are short-lived by design; refresh tokens are the persistent credential and must be protected accordingly. If both are stolen, the attacker has full access until the refresh token is detected and revoked.

> [!question]- Q3. Explain the difference between HS256 and RS256 for JWT signing. When would you choose each, and what are the trade-offs?
**Answer:** HS256 (HMAC-SHA256): symmetric algorithm. The same secret key is used to sign AND verify tokens. Fast (symmetric crypto), simple, good for single-service applications. Trade-off: any service that can verify tokens can also forge them (they have the signing key). If you have microservices, all services share the same secret — if one is compromised, all tokens can be forged. RS256 (RSA-SHA256): asymmetric algorithm. A private key signs tokens, a public key verifies them. The private key is held only by the auth service. Public keys can be freely distributed to any service that needs to verify tokens. Trade-off: slower (asymmetric crypto), more complex key management, but secure for microservices — verifying services can't forge tokens. Choice: HS256 for single-service or monolithic apps (simpler, faster). RS256 for microservices or when token verification is done by services that shouldn't be able to sign tokens. For most FastAPI applications starting out, HS256 is sufficient. Migrate to RS256 when you introduce multiple services that need to verify tokens.

> [!question]- Q4. You need to implement "logout all devices" for a user. The user has multiple active sessions (multiple refresh tokens) across different devices. Design the implementation.
**Answer:** The challenge: JWT access tokens are stateless and can't be individually revoked. The solution targets refresh tokens, which are stored in the database. Approach 1: Delete all refresh tokens for the user. All devices lose their refresh tokens. Existing access tokens remain valid until expiration (15-30min), but can't be refreshed. After expiration, all devices must re-authenticate. Approach 2: Token versioning. Store a token_version column in the user table. Include it in JWT payload. On "logout all devices", increment the token_version. All existing tokens (access and refresh) have the old version and are rejected on next verification. Both approaches work. Approach 1 is simpler (just delete rows). Approach 2 is more comprehensive (revokes access tokens immediately on next verification, not just refresh tokens). Recommended: combine both. On "logout all devices": (1) Delete all refresh tokens for the user. (2) Increment token_version. This immediately invalidates all sessions — access tokens fail on next verification (version mismatch), and refresh tokens are deleted (can't get new access tokens). The user must log in again on all devices.

> [!question]- Q5. A FastAPI API uses JWT for auth. The JWT secret is accidentally committed to a public GitHub repository. Describe the incident response plan.
**Answer:** Immediate actions (within minutes): (1) Rotate the JWT secret — generate a new random key, update environment variables, restart all services. All existing tokens become invalid. Users must re-authenticate. (2) Check GitHub audit logs — did anyone clone the repo before the secret was removed? (3) Remove the secret from Git history — use `git filter-branch` or BFG Repo Cleaner to purge the secret from all commits. Force-push. (4) If the repo is public, notify users that their sessions may have been compromised. (5) Check access logs for suspicious activity during the exposure window. (6) Add pre-commit hooks (detect-secrets, git-secrets) to prevent future secret leaks. (7) Use a secrets manager (HashiCorp Vault, AWS Secrets Manager) instead of environment variables for production secrets. (8) Review who had access to the repo and the deployment environment. The key: rotate immediately, assume all tokens issued with the old key are compromised, force re-authentication, and prevent recurrence with tooling and process changes.

## Related
[[request-response-lifecycle]]
[[dependency-injection]]
[[middleware]]
[[env-and-config-management]]
[[cors-and-security-headers]]

#status/new