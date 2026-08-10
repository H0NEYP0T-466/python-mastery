# Env and Config Management

## What it is
Environment variables are the standard way to configure applications across environments (development, staging, production) without changing code. FastAPI and Pydantic provide tools for loading, validating, and structuring environment variables. This file covers the 12-factor app pattern, Pydantic's `BaseSettings`, environment variable naming conventions, secret management, multi-environment config, and the gotchas that cause "works locally, fails in production" bugs.

## Why it matters
Hardcoded credentials and environment-specific config is one of the most common production failures. A database URL that works locally but points to production, a secret key that's the same across environments, a feature flag that's always on — these cause outages, security breaches, and wasted debugging time. In interviews, config questions test whether you understand the 12-factor app pattern, secret management, and environment isolation. For your work — deploying APIs, managing ML model endpoints, running services — config management is foundational.

## Core example

### Pydantic BaseSettings — the modern approach

```python
from pydantic import BaseSettings, Field, PostgresDsn, RedisDsn, HttpUrl
from typing import Optional

class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    # App configuration
    app_name: str = Field("MyAPI", env="APP_NAME")
    debug: bool = Field(False, env="DEBUG")
    version: str = Field("1.0.0", env="API_VERSION")
    
    # Server configuration
    host: str = Field("0.0.0.0", env="HOST")
    port: int = Field(8000, env="PORT")
    workers: int = Field(4, env="WORKERS")
    
    # Database configuration
    database_url: PostgresDsn = Field(
        "postgresql://user:pass@localhost/mydb",
        env="DATABASE_URL",
    )
    database_pool_size: int = Field(10, env="DB_POOL_SIZE")
    database_echo: bool = Field(False, env="DB_ECHO")
    
    # Redis configuration
    redis_url: RedisDsn = Field("redis://localhost:6379", env="REDIS_URL")
    
    # JWT configuration
    jwt_secret_key: str = Field(..., env="JWT_SECRET_KEY")  # Required
    jwt_algorithm: str = Field("HS256", env="JWT_ALGORITHM")
    jwt_access_expire_minutes: int = Field(30, env="JWT_ACCESS_EXPIRE_MINUTES")
    
    # CORS configuration
    cors_origins: list[HttpUrl] = Field([], env="CORS_ORIGINS")
    
    # Logging configuration
    log_level: str = Field("INFO", env="LOG_LEVEL")
    log_json: bool = Field(False, env="LOG_JSON")
    
    # Feature flags
    feature_new_ui: bool = Field(False, env="FEATURE_NEW_UI")
    feature_rate_limit: bool = Field(True, env="FEATURE_RATE_LIMIT")
    
    # Third-party API keys (all required in production)
    openai_api_key: Optional[str] = Field(None, env="OPENAI_API_KEY")
    stripe_api_key: Optional[str] = Field(None, env="STRIPE_API_KEY")
    
    class Config:
        env_file = ".env"  # Load from .env file
        env_file_encoding = "utf-8"
        case_sensitive = False  # Env vars are case-insensitive
        extra = "forbid"  # Reject unknown env vars (catches typos)

# Usage — instantiate once at startup
settings = Settings()

# In your FastAPI app:
from fastapi import FastAPI
app = FastAPI(title=settings.app_name, version=settings.version)

# Access settings anywhere:
# settings.database_url, settings.jwt_secret_key, etc.
```

### The .env file — local development only

```ini
# .env — local development configuration
# NEVER commit this to version control!
# Add .env to .gitignore

# App
APP_NAME=MyAPI (Dev)
DEBUG=true
PORT=8001

# Database — use a local dev database, NOT production
DATABASE_URL=postgresql://dev_user:dev_pass@localhost/mydb_dev

# Redis
REDIS_URL=redis://localhost:6379/1

# JWT — use a different secret for development
JWT_SECRET_KEY=dev-secret-change-in-production
JWT_ACCESS_EXPIRE_MINUTES=60

# CORS — allow all for development
CORS_ORIGINS=http://localhost:3000,http://localhost:5173

# Logging
LOG_LEVEL=DEBUG
LOG_JSON=false

# Feature flags
FEATURE_NEW_UI=true
FEATURE_RATE_LIMIT=false

# External APIs — use test keys
OPENAI_API_KEY=sk-test-xxx
STRIPE_API_KEY=pk_test_xxx
```

### The .env.example file — what you commit

```ini
# .env.example — template for developers
# Copy this to .env and fill in the values

# App
APP_NAME=MyAPI
DEBUG=false
PORT=8000

# Database
DATABASE_URL=postgresql://user:pass@localhost/mydb

# Redis
REDIS_URL=redis://localhost:6379

# JWT
JWT_SECRET_KEY=change-me-in-production
JWT_ACCESS_EXPIRE_MINUTES=30

# CORS (comma-separated URLs)
CORS_ORIGINS=https://myapp.com

# Logging
LOG_LEVEL=INFO
LOG_JSON=false

# External APIs
OPENAI_API_KEY=
STRIPE_API_KEY=
```

### Multi-environment configuration — dev/staging/prod

```python
# Instead of one giant Settings class, use environment-specific subclasses

class BaseSettings(BaseSettings):
    """Common settings for all environments"""
    app_name: str
    debug: bool
    database_url: PostgresDsn
    redis_url: RedisDsn
    jwt_secret_key: str
    
    class Config:
        env_file = ".env"
        extra = "forbid"

class DevSettings(BaseSettings):
    """Development environment settings"""
    debug: bool = True
    database_url: PostgresDsn = "postgresql://dev:dev@localhost/mydb_dev"
    jwt_secret_key: str = "dev-secret"
    
    class Config:
        env_file = ".env.dev"

class ProdSettings(BaseSettings):
    """Production environment settings"""
    debug: bool = False
    # No defaults for production — all must be from env vars
    # database_url: no default — must be set via env
    # jwt_secret_key: no default — must be set via env
    
    class Config:
        env_file = ".env.prod"

# Environment detection — load the right settings based on ENVIRONMENT env var
import os

def get_settings() -> BaseSettings:
    env = os.environ.get("ENVIRONMENT", "dev")
    
    if env == "production":
        return ProdSettings()
    elif env == "staging":
        return StagingSettings()
    else:
        return DevSettings()

settings = get_settings()

# Alternative: use a single Settings class with environment-aware defaults
class Settings(BaseSettings):
    environment: str = Field("dev", env="ENVIRONMENT")
    
    # Environment-specific defaults using root_validator
    @model_validator(mode="after")
    def validate_environment(self):
        if self.environment == "production" and self.debug:
            raise ValueError("DEBUG must be false in production")
        if self.environment == "production" and self.jwt_secret_key == "change-me":
            raise ValueError("JWT_SECRET_KEY must be set in production")
        return self
```

### Secret management — beyond environment variables

```python
# Environment variables are the standard, but for production,
# consider a proper secrets manager.

# Option 1: HashiCorp Vault
import hvac

client = hvac.Client(url="http://vault:8200", token=VAULT_TOKEN)

# Read secret from Vault
secret = client.secrets.kv.v2.read_secret_version(
    path="myapp/jwt"
)
jwt_secret = secret["data"]["data"]["secret_key"]

# Option 2: AWS Secrets Manager
import boto3

client = boto3.client("secretsmanager")
response = client.get_secret_value(SecretId="myapp/jwt")
jwt_secret = response["SecretString"]

# Option 3: GCP Secret Manager
from google.cloud import secretmanager

client = secretmanager.SecretManagerServiceClient()
name = f"projects/my-project/secrets/jwt-secret/versions/latest"
response = client.access_secret_version(request={"name": name})
jwt_secret = response.payload.data.decode("UTF-8")

# Option 4: Azure Key Vault
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient

credential = DefaultAzureCredential()
client = SecretClient(vault_url="https://myvault.vault.azure.net", credential=credential)
jwt_secret = client.get_secret("jwt-secret").value

# Integration with Pydantic Settings:
# Load secrets from the manager and pass them as environment variables
# or override them after loading the base settings.

import os
from pydantic import BaseSettings

def load_from_vault():
    """Load secrets from Vault and set as environment variables"""
    client = hvac.Client(url=VAULT_TOKEN)
    secrets = client.secrets.kv.v2.read_secret_version(path="myapp")
    for key, value in secrets["data"]["data"].items():
        os.environ[key.upper()] = value

# Load secrets first, then load settings
load_from_vault()
settings = Settings()  # Now picks up secrets from env vars

# The pattern: secrets manager → environment variables → Pydantic Settings.
# This keeps your code simple (just reads env vars) while using a
# proper secrets manager for storage and rotation.
```

### Pydantic v2 Settings changes

```python
# Pydantic v2 changed the Settings API:

# v1 (old):
# class Settings(BaseSettings):
#     class Config:
#         env_file = ".env"
#         case_sensitive = False

# v2 (new):
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="forbid",
    )

# The key changes:
# 1. Settings is now in a separate package: pip install pydantic-settings
# 2. Config class → model_config = SettingsConfigDict(...)
# 3. env field name → Field(..., env="VAR_NAME") still works
# 4. SettingsConfigDict has additional options:
#    - env_prefix: prefix for all env vars (e.g., "MYAPP_")
#    - env_nested_delimiter: for nested settings (e.g., "DB__HOST")
#    - env_parse_*: custom parsing for specific types

# Nested settings with delimiter:
class DatabaseSettings(BaseSettings):
    host: str = "localhost"
    port: int = 5432
    name: str = "mydb"

class Settings(BaseSettings):
    db: DatabaseSettings  # Nested
    
    model_config = SettingsConfigDict(
        env_nested_delimiter="__",  # DB__HOST, DB__PORT
    )

# Environment variables:
# DB__HOST=prod-db.example.com
# DB__PORT=5432
# DB__NAME=production

# Settings().db.host → "prod-db.example.com"
```

### Environment variable naming conventions

```python
# Standard conventions for environment variable names:

# 1. UPPERCASE with underscores
# DATABASE_URL, JWT_SECRET_KEY, DEBUG

# 2. Prefix with app name (avoids conflicts)
# MYAPP_DATABASE_URL, MYAPP_JWT_SECRET_KEY

# 3. Environment-specific suffix (for multi-env files)
# DATABASE_URL_DEV, DATABASE_URL_PROD

# 4. Namespaced with double underscore (for nested config)
# DATABASE__HOST, DATABASE__PORT

# Recommended convention for FastAPI apps:
# - Use UPPERCASE with underscores
# - Prefix with app name if deploying alongside other apps
# - Use the same name as the Python field (uppercase)
# - For nested settings, use double underscore delimiter

# Example:
# APP_NAME=MyAPI
# DATABASE_URL=postgresql://...
# DATABASE_POOL_SIZE=10
# JWT_SECRET_KEY=...
# CORS_ORIGINS=https://...

# In Pydantic Settings with prefix:
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MYAPP_",  # All env vars must have MYAPP_ prefix
        env_file=".env",
    )

# Now env vars are: MYAPP_DATABASE_URL, MYAPP_JWT_SECRET_KEY, etc.
```

### Overriding settings in tests

```python
# In tests, you often want to override settings (use test DB, disable auth).

# Method 1: Environment variable override (simplest)
# Set env vars before importing settings
import os
os.environ["DATABASE_URL"] = "postgresql://test:test@localhost/testdb"
os.environ["DEBUG"] = "true"

# Now import the settings (after setting env vars)
from myapp.settings import settings

# Method 2: Dependency override (FastAPI-specific)
# Override the settings dependency in tests
from fastapi.testclient import TestClient
from myapp.main import app

test_settings = Settings(
    database_url="postgresql://test:test@localhost/testdb",
    debug=True,
    jwt_secret_key="test-secret",
)

# Override the settings dependency
app.dependency_overrides[get_settings] = lambda: test_settings

client = TestClient(app)
# ... run tests ...

app.dependency_overrides.clear()

# Method 3: Context manager for test settings
from contextlib import contextmanager

@contextmanager
def override_settings(**kwargs):
    original_values = {}
    for key, value in kwargs.items():
        original_values[key] = os.environ.get(key)
        os.environ[key] = str(value)
    
    # Reload settings
    import myapp.settings
    importlib.reload(myapp.settings)
    
    try:
        yield myapp.settings
    finally:
        # Restore original values
        for key, original_value in original_values.items():
            if original_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = original_value
        importlib.reload(myapp.settings)

# Usage:
# with override_settings(DATABASE_URL="postgresql://test:test@localhost/testdb"):
#     response = client.get("/items/")
```

## Common mistakes / gotchas

- **Committing .env to Git** — .env contains secrets. Always add .env to .gitignore. Use .env.example as the committed template. Use pre-commit hooks (detect-secrets) to prevent accidental secret commits.
- **Using the same secret across environments** — dev, staging, and prod should have different JWT secrets, database URLs, and API keys. If dev is compromised, prod is not. Use environment-specific settings or separate .env files.
- **Missing required settings in production** — if a setting has no default and isn't set in production, the app crashes at startup. Use `Field(...)` (no default) for required settings and validate at startup.
- **Case sensitivity confusion** — environment variables are case-sensitive on Linux but case-insensitive on Windows. Use consistent uppercase naming. Pydantic's `case_sensitive=False` (default) helps but doesn't fix OS-level issues.
- **Loading .env after importing settings** — .env is loaded when the Settings class is instantiated. If you set environment variables after importing settings, they won't be picked up. Set env vars before instantiating Settings, or reload the module.
- **Overusing environment variables for everything** — not everything should be an env var. Use env vars for configuration that changes between environments (database URLs, secrets, feature flags). Hardcode things that never change (API route paths, model class names).
- **Not validating settings at startup** — if a setting is wrong (invalid database URL, missing secret), the app should fail fast at startup, not at runtime when a request hits. Use Pydantic validation (type hints, Field constraints) to catch errors early.
- **Ignoring the `extra="forbid"` setting** — without `extra="forbid"`, typos in env var names (DATABSE_URL instead of DATABASE_URL) are silently ignored. The setting uses its default, and you never notice the typo. Use `extra="forbid"` to catch these.

## Practice

> [!question]- Q1. Design a configuration system for a FastAPI microservices architecture with 5 services. Each service needs: database URL, Redis URL, JWT secret (shared for verification), feature flags, and service-specific config. How do you manage shared vs service-specific config?
**Answer:** Use a layered approach: (1) **Shared config** (JWT public key, common feature flags) — stored in a shared secrets manager (Vault path `shared/jwt`, `shared/feature-flags`) or environment variables inherited by all services. (2) **Service-specific config** — each service has its own settings class loading from environment variables prefixed with the service name (e.g., `AUTH_DATABASE_URL`, `PAYMENTS_DATABASE_URL`). (3) **Environment-specific** — use separate .env files per environment (`.env.dev`, `.env.staging`, `.env.prod`) or a config service that serves environment-specific settings. (4) **Secrets** — use a secrets manager (Vault) with separate paths per service (`secrets/auth`, `secrets/payments`). Each service only has access to its own secret path. The key design: shared config is read-only and distributed to all services. Service-specific config is isolated. Secrets are managed by a dedicated service with access control. Environment variables are the interface; the source can be .env (development), secrets manager (production), or cloud parameter store.

> [!question]- Q2. Your FastAPI app uses Pydantic Settings. In production, the app starts but returns 500 errors on all requests. The logs show "database connection failed." The DATABASE_URL env var looks correct. Diagnose the issue.
**Answer:** Step 1: Check if the env var is actually being read. Add a startup log that prints the database URL (redacting password). If it shows the default value instead of the production value, the env var isn't being loaded — check .env file location, env var name case, or container environment. Step 2: Check if the database is reachable from the production network. The URL might be correct but the DB might be on a different VPC or behind a firewall. Step 3: Check connection pool settings — pool_size too high for the DB's max_connections, causing connection refused. Step 4: Check if the database credentials have expired or been rotated. Step 5: Check if the async driver is installed (asyncpg for PostgreSQL+asyncpg). If using sync driver with async session, it fails. The most common cause: the env var isn't actually being read by the Settings class (wrong file, wrong name, loaded before env var was set). Always log the loaded settings at startup (without secrets) for debugging.

> [!question]- Q3. Compare the approaches of using .env files, environment variables directly, and a secrets manager (Vault/AWS Secrets Manager). When would you use each, and what's the production best practice?
**Answer:** .env files: simple, local development only. Pros: easy to set up, version-controlled template (.env.example). Cons: secrets in files, not suitable for production, can be committed accidentally. Use for: local development, testing. Environment variables directly: standard 12-factor app approach. Pros: no files, supported by all platforms, easy to change. Cons: visible in process lists, can be logged, no access control, no rotation. Use for: simple deployments, PaaS (Heroku, Render), container orchestration (Kubernetes envFrom). Secrets manager (Vault, AWS SM, GCP SM): production-grade. Pros: encryption at rest, access control, audit logging, automatic rotation, dynamic secrets. Cons: adds infrastructure complexity, network dependency, cost. Use for: production, regulated environments, multi-service architectures. Production best practice: secrets manager as the source of truth → secrets injected as environment variables at runtime (or read by the app at startup) → Pydantic Settings validates and structures them. For development: .env files with .env.example template. Never use .env in production. Never commit secrets to version control.

> [!question]- Q4. You need to support both a monolithic config (single Settings class) and a modular config (separate settings per module). Design both approaches and compare trade-offs.
**Answer:** Monolithic (single Settings class):
```python
class Settings(BaseSettings):
    # Everything in one class
    database_url: str
    redis_url: str
    jwt_secret: str
    stripe_key: str
    openai_key: str
    # ... 50+ fields ...
```
Pros: single source of truth, easy to see all config at once, simple to load. Cons: becomes unwieldy at scale, all modules depend on all settings, hard to test individual modules, settings class grows unbounded. Modular (separate settings per module):
```python
class DatabaseSettings(BaseSettings):
    url: str
    pool_size: int = 10

class AuthSettings(BaseSettings):
    jwt_secret: str
    access_expire_minutes: int = 30

class PaymentSettings(BaseSettings):
    stripe_key: str
    webhook_secret: str

# Compose in main Settings:
class Settings(BaseSettings):
    db: DatabaseSettings
    auth: AuthSettings
    payments: PaymentSettings
    model_config = SettingsConfigDict(env_nested_delimiter="__")
```
Pros: modular, each module owns its settings, testable individually, scalable. Cons: more complex, nested env var names (DB__URL, AUTH__JWT_SECRET), need to compose at startup. Recommendation: start monolithic for small apps (< 20 settings), migrate to modular as the app grows. The modular approach is better for teams (each team owns their settings module) and for large applications.

> [!question]- Q5. A developer on your team accidentally committed a .env file with production secrets to Git. The repo is public. Describe the step-by-step remediation.
**Answer:** Immediate (within 1 hour): (1) Rotate ALL secrets that were exposed — database passwords, JWT secrets, API keys, SSH keys. Assume they're compromised. (2) Remove the file from Git history: `git filter-branch --tree-filter 'rm -f .env' HEAD` or use BFG Repo Cleaner. Force-push. (3) If the repo was public, notify GitHub support to remove the file from cached versions. (4) Check access logs for the exposed services — were the secrets used by unauthorized parties? (5) Revoke and regenerate API keys, rotate database passwords, change JWT secret (invalidating all user sessions). Short-term (within 1 day): (6) Add .env to .gitignore if not already there. (7) Add pre-commit hook (detect-secrets, git-secrets) to prevent future commits. (8) Audit all team members' local copies — ensure they've removed the file. (9) Review GitHub audit logs for unauthorized access. Long-term (within 1 week): (10) Move all secrets to a secrets manager (Vault, AWS SM). (11) Implement secret rotation automation. (12) Train the team on secret management best practices. (13) Add CI/CD pipeline scanning for secrets. The key: rotate everything immediately, remove from history, prevent recurrence with tooling and process.

## Related
[[env-and-config-management]]
[[auth-oauth2-jwt]]
[[logging-and-monitoring]]
[[deployment-docker-uvicorn]]

#status/new