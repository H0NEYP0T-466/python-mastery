# Project Folder Structure

## What it is
How you organize a FastAPI project matters more than people think. A good structure makes it easy to find code, add features, test components, and onboard new developers. A bad structure becomes a tangled mess where everything depends on everything, tests are impossible, and adding a feature means touching 10 files. This file covers multiple structural approaches — from simple to scaled — with the reasoning behind each decision, not just a tree diagram.

## Why it matters
In interviews, system design questions about API architecture assume you understand project organization. In production, a bad structure slows down every feature and makes refactoring terrifying. For your work — building APIs that evolve over time — the structure you choose early determines how painful growth becomes. Starting with the right pattern saves months of refactoring later.

## Core example

### The minimal structure — single file (good for prototypes, bad for anything else)

```
myapp/
├── main.py          # Everything — models, routes, config, DB
├── requirements.txt
└── .env

# main.py:
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class Item(BaseModel):
    name: str

@app.post("/items/")
def create_item(item: Item):
    return item

# When to use: prototypes, tutorials, single-endpoint microservices.
# When NOT to use: any app with more than 2-3 endpoints, any app
# that will grow, any app with a team.
```

### The functional structure — organized by route type (good for small-to-medium apps)

```
myapp/
├── app/
│   ├── __init__.py
│   ├── main.py              # App entry point, creates FastAPI instance
│   ├── config.py            # Settings, config loading
│   ├── database.py          # DB engine, session factory
│   ├── dependencies.py      # Shared dependencies (auth, DB session)
│   ├── exceptions.py        # Custom exception handlers
│   ├── middleware.py        # Custom middleware
│   │
│   ├── models/              # Database models (SQLAlchemy)
│   │   ├── __init__.py
│   │   ├── user.py
│   │   ├── post.py
│   │   └── comment.py
│   │
│   ├── schemas/             # Pydantic models (request/response)
│   │   ├── __init__.py
│   │   ├── user.py
│   │   ├── post.py
│   │   └── comment.py
│   │
│   ├── crud/                # Database operations
│   │   ├── __init__.py
│   │   ├── user.py
│   │   ├── post.py
│   │   └── comment.py
│   │
│   ├── routers/             # API route definitions
│   │   ├── __init__.py
│   │   ├── user.py
│   │   ├── post.py
│   │   └── comment.py
│   │
│   └── services/            # Business logic (optional layer)
│       ├── __init__.py
│       ├── email.py
│       └── auth.py
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py          # Shared test fixtures
│   ├── test_user.py
│   └── test_post.py
│
├── requirements.txt
├── .env
└── .env.example
```

**Why this works:**
- **Separation of concerns**: models (DB), schemas (API), CRUD (data access), routers (HTTP) are separate layers
- **Testability**: each layer can be tested independently
- **Scalability**: add new entities by adding files, not modifying existing ones
- **Team-friendly**: different people can work on different entities without merge conflicts

**The key relationships:**
```
Request → Router → Service/CRUD → DB Model
                    ↓
              Response Schema
```

Router handles HTTP (params, auth, response). CRUD handles data access. Service handles business logic. Models handle DB schema. Schemas handle API contracts. Each layer talks only to adjacent layers.

### The domain-driven structure — organized by bounded context (good for large apps, microservices)

```
myapp/
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── database.py
│   │
│   ├── shared/          # Cross-cutting concerns
│   │   ├── __init__.py
│   │   ├── dependencies.py
│   │   ├── exceptions.py
│   │   ├── middleware.py
│   │   └── utils.py
│   │
│   ├── users/           # Bounded context: User management
│   │   ├── __init__.py
│   │   ├── models.py
│   │   ├── schemas.py
│   │   ├── crud.py
│   │   ├── router.py
│   │   └── services.py
│   │
│   ├── posts/           # Bounded context: Content
│   │   ├── __init__.py
│   │   ├── models.py
│   │   ├── schemas.py
│   │   ├── crud.py
│   │   ├── router.py
│   │   └── services.py
│   │
│   ├── payments/        # Bounded context: Payments
│   │   ├── __init__.py
│   │   ├── models.py
│   │   ├── schemas.py
│   │   ├── crud.py
│   │   ├── router.py
│   │   └── services.py
│   │
│   └── analytics/       # Bounded context: Analytics
│       ├── __init__.py
│       ├── models.py
│       ├── schemas.py
│       ├── crud.py
│       ├── router.py
│       └── services.py
│
├── tests/
│   ├── conftest.py
│   ├── users/
│   ├── posts/
│   ├── payments/
│   └── analytics/
│
└── ...
```

**When to use domain-driven:**
- Multiple teams owning different parts of the app
- Clear business domains (users, payments, content, analytics)
- Each domain has its own data and business rules
- Planning to split into microservices eventually

**The advantage over functional structure:**
- Each domain is self-contained — models, schemas, CRUD, router live together
- Easier to extract a domain into a microservice later
- Teams can work on different domains without coordination
- Clearer ownership — "the payments team owns the payments directory"

### The API router pattern — how routes are organized

```python
# app/routers/user.py
from fastapi import APIRouter, Depends, HTTPException
from .. import schemas, crud, dependencies

router = APIRouter(
    prefix="/users",
    tags=["users"],
    dependencies=[Depends(dependencies.get_current_user)],
)

@router.get("/", response_model=list[schemas.User])
async def list_users(skip: int = 0, limit: int = 10, db: Session = Depends(dependencies.get_db)):
    return crud.get_users(db, skip=skip, limit=limit)

@router.get("/{user_id}", response_model=schemas.User)
async def get_user(user_id: int, db: Session = Depends(dependities.get_db)):
    user = crud.get_user(db, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    return user

@router.post("/", response_model=schemas.User, status_code=201)
async def create_user(user: schemas.UserCreate, db: Session = Depends(dependencies.get_db)):
    return crud.create_user(db, user)

# app/main.py
from fastapi import FastAPI
from .routers import user, post

app = FastAPI()

app.include_router(user.router)
app.include_router(post.router)

# Optional: API versioning
# app.include_router(user.router, prefix="/api/v1")

@app.get("/health")
async def health():
    return {"status": "ok"}
```

### The service layer — when you need it and when you don't

```python
# The service layer sits between routers and CRUD. It handles business logic
# that doesn't fit in a single CRUD operation.

# When you NEED a service layer:
# - Business logic spans multiple models (e.g., creating an order
#   involves inventory check, payment, order creation, notification)
# - You need to call external APIs as part of a business operation
# - You have complex validation that spans multiple entities
# - You want to reuse business logic across different API endpoints
# - You plan to expose the same logic via different interfaces
#   (API + CLI + websockets)

# When you DON'T need a service layer:
# - Simple CRUD — router → CRUD → DB is enough
# - Each endpoint maps to a single database operation
# - No cross-entity business logic

# Example — order creation with service layer:

# app/services/order.py
class OrderService:
    def __init__(self, db: Session, payment_gateway: PaymentGateway):
        self.db = db
        self.payment_gateway = payment_gateway
    
    def create_order(self, user_id: int, order_data: OrderCreate) -> Order:
        # Business logic that spans multiple operations
        with self.db.begin():  # Transaction
            # 1. Check inventory
            inventory = crud.get_inventory(self.db, order_data.item_id)
            if inventory.quantity < order_data.quantity:
                raise HTTPException(400, "Insufficient stock")
            
            # 2. Charge payment
            charge = self.payment_gateway.charge(
                user_id, order_data.total
            )
            if not charge.success:
                raise HTTPException(400, "Payment failed")
            
            # 3. Create order
            order = crud.create_order(self.db, order_data, user_id)
            
            # 4. Update inventory
            crud.update_inventory(self.db, order_data.item_id, -order_data.quantity)
            
            # 5. Send notification (async, not in transaction)
            # Using background task or event bus
            send_order_created_notification(order)
            
            return order

# app/routers/order.py
router = APIRouter()

@router.post("/", response_model=Order)
async def create_order(
    order_data: OrderCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Service layer handles the business logic
    payment_gateway = StripePaymentGateway(api_key=settings.stripe_key)
    service = OrderService(db, payment_gateway)
    return service.create_order(current_user.id, order_data)
```

### The dependencies file — centralizing shared dependencies

```python
# app/dependencies.py
from fastapi import Depends, HTTPException, Security
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from .database import get_db
from .crud import get_user_by_username

oauth2 = OAuth2PasswordBearer(tokenUrl="/auth/login")

async def get_current_user(token: str = Depends(oauth2), db: AsyncSession = Depends(get_db)):
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        username = payload.get("sub")
        if username is None:
            raise HTTPException(401, "Invalid token")
    except JWTError:
        raise HTTPException(401, "Invalid token")
    
    user = await get_user_by_username(db, username)
    if user is None:
        raise HTTPException(401, "User not found")
    if user.disabled:
        raise HTTPException(403, "Disabled user")
    return user

async def get_admin_user(current_user: User = Depends(get_current_user)):
    if current_user.role != "admin":
        raise HTTPException(403, "Admin only")
    return current_user

def get_pagination(skip: int = 0, limit: int = Query(10, le=100)):
    return {"skip": skip, "limit": limit}

# Centralizing dependencies in one file makes them easy to find,
# test, and reuse. But for large apps, consider splitting by domain:
# app/users/dependencies.py, app/posts/dependencies.py, etc.
```

### The exceptions file — centralized error handling

```python
# app/exceptions.py
from fastapi import Request, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
import logging

logger = logging.getLogger(__name__)

# Custom exception classes
class AppException(Exception):
    """Base application exception"""
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail

class NotFoundException(AppException):
    def __init__(self, detail: str = "Not found"):
        super().__init__(404, detail)

class ForbiddenException(AppException):
    def __init__(self, detail: str = "Forbidden"):
        super().__init__(403, detail)

class ValidationException(AppException):
    def __init__(self, detail: str = "Validation error"):
        super().__init__(422, detail)

# Exception handlers — register in main.py
async def app_exception_handler(request: Request, exc: AppException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail},
    )

async def validation_exception_handler(request: Request, exc: RequestValidationError):
    # Format validation errors nicely
    errors = []
    for err in exc.errors():
        errors.append({
            "field": ".".join(str(loc) for loc in err["loc"]),
            "message": err["msg"],
            "code": err["type"],
        })
    return JSONResponse(
        status_code=422,
        content={"error": "Validation failed", "details": errors},
    )

async def unhandled_exception_handler(request: Request, exc: Exception):
    # Log the full error for debugging
    logger.error(f"Unhandled error: {exc}", exc_info=True)
    
    # Return generic error to client (never expose internals)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error"},
    )

# Register in main.py:
# app.add_exception_handler(AppException, app_exception_handler)
# app.add_exception_handler(RequestValidationError, validation_exception_handler)
# app.add_exception_handler(Exception, unhandled_exception_handler)
```

## Common mistakes / gotchas

- **Putting everything in main.py** — works for tutorials, unmanageable for real apps. Separate concerns early.
- **Circular imports** — models importing schemas importing crud importing models. Solve by using `TYPE_CHECKING` for type hints, importing inside functions, or restructuring to eliminate the cycle.
- **No service layer when business logic is complex** — routers full of business logic are hard to test and reuse. Add a service layer when business logic spans multiple operations.
- **Too many layers** — adding a service layer for simple CRUD is overengineering. Start simple, add layers as needed.
- **Inconsistent naming** — mixing `models`, `db`, `entities` for the same concept. Pick one naming convention and stick to it.
- **Tests not mirroring the app structure** — if app has `app/users/`, tests should have `tests/users/`. Makes it easy to find tests for any module.
- **Hardcoded paths** — `from ..models.user import User` in deep nested modules is fragile. Use absolute imports with a proper package structure and `PYTHONPATH` or `pyproject.toml` paths.

## Practice

> [!question]- Q1. You're starting a new FastAPI project that will eventually have 50+ endpoints, 3 teams working on different features, and a plan to split into microservices in 12 months. Choose a folder structure and justify each decision.
**Answer:** Use the domain-driven structure with bounded contexts. Each team owns a domain directory (users, payments, content, analytics, etc.) with models, schemas, crud, router, and services inside. This enables: (1) Team ownership — each team works in their own directory with minimal merge conflicts. (2) Easy microservice extraction — each domain is already self-contained with its own models and router. Moving to a separate service means moving a directory. (3) Shared code goes in `app/shared/` (dependencies, middleware, exceptions, utilities) — used by all domains but owned by a shared team or rotating ownership. (4) Database is shared initially (single DB) but each domain owns its tables — prepares for database-per-service later. (5) API gateway pattern at the main level — routes are mounted by domain, making it easy to route to different services later. The key principle: structure for where you'll be in 12 months, not where you are today. But don't over-engineer — start with the domain structure from day 1, add service layers as business logic demands, and keep shared concerns minimal.

> [!question]- Q2. Your FastAPI app has models in `app/models/` and schemas in `app/schemas/`. Both need to reference each other (model → schema for response, schema → model for creation). This causes circular imports. How do you fix it?
**Answer:** Three approaches: (1) **Use `TYPE_CHECKING`** — import types only for type hints, not at runtime. In models: `from typing import TYPE_CHECKING` then `if TYPE_CHECKING: from app.schemas import UserCreate`. In schemas: `if TYPE_CHECKING: from app.models import User`. This breaks the runtime circular import because the imports only happen during type checking. (2) **Import inside functions** — delay imports until they're needed inside functions, not at module level. This works but is less clean. (3) **Use string forward references** — in Pydantic models, use string annotations: `"User"` instead of `User`. Pydantic resolves these after all models are defined. The recommended approach: `TYPE_CHECKING` for cross-references, combined with Pydantic's `model_config = ConfigDict(from_attributes=True)` for converting models to schemas. The circular dependency between models and schemas is a common anti-pattern — if you find yourself needing both directions, reconsider whether schemas should reference models at all. Often, schemas only need field types (primitives), not model references.

> [!question]- Q3. Compare the functional structure vs domain-driven structure for a FastAPI project. When do you migrate from one to the other, and what's the migration path?
**Answer:** Functional structure: organized by layer (models/, schemas/, crud/, routers/). Good for small-to-medium apps (< 20 endpoints, single team). Easy to understand, clear separation of concerns. Becomes unwieldy when: files in each layer grow to 50+ modules, multiple teams need to coordinate on every change, related code is scattered across layers. Domain-driven structure: organized by domain (users/, posts/, payments/). Good for large apps (50+ endpoints, multiple teams, microservice plans). Each domain is self-contained. Harder to understand initially, requires more discipline. Migration path: (1) Start with functional structure. (2) When a single layer file exceeds 10-15 modules, group related modules into subdirectories within that layer. (3) When 3+ teams are working on the same layer files frequently, migrate to domain-driven: take one domain at a time, move its models/schemas/crud/router into a new domain directory. (4) Update imports gradually — use compatibility shims during migration. (5) Once all domains are migrated, remove the old layer directories. Migration is gradual — don't rewrite everything at once. Start with the most independent domain (least cross-references), move it, verify, then move the next.

> [!question]- Q4. You have a FastAPI app with a service layer. A new team member wants to call CRUD directly from the router, bypassing the service layer, for a "simple" endpoint. What do you tell them?
**Answer:** The rule: if the endpoint is truly a single CRUD operation with no business logic, calling CRUD directly from the router is acceptable. But be disciplined about what "simple" means. Criteria for direct CRUD: (1) Single database operation (get by ID, list with pagination, create, update, delete). (2) No cross-entity validation or business rules. (3) No external API calls. (4) No side effects (emails, notifications, cache invalidation). (5) No transaction spanning multiple operations. If ANY of these apply, use the service layer. The danger: "just one simple endpoint" becomes 20 direct CRUD calls, and the service layer becomes meaningless. The team loses the benefits of centralized business logic, testing consistency, and easy migration. Enforce the rule through code review: if a router handler has more than one CRUD call, or any business logic, it belongs in the service layer. Document this in the project's CONTRIBUTING.md. The service layer exists to protect business logic from scattering — don't let it erode.

> [!question]- Q5. Design a folder structure for a FastAPI app that serves ML model inference (like your DINOv2/GPT-2 work). The API needs: model loading, batch inference, model versioning, A/B testing between models, and health checks for model status.
**Answer:**
```
ml-api/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── dependencies.py
│   │
│   ├── models/          # Pydantic schemas (not ML models)
│   │   ├── inference.py  # Request/response schemas
│   │   └── health.py
│   │
│   ├── ml/              # ML-specific logic
│   │   ├── __init__.py
│   │   ├── loader.py    # Model loading (from disk, S3, HF Hub)
│   │   ├── registry.py  # Model registry (version → model instance)
│   │   ├── predictor.py # Inference wrapper (batch, single)
│   │   ├── preproc.py   # Preprocessing (tokenization, image transform)
│   │   └── postproc.py  # Postprocessing (logits → labels, etc.)
│   │
│   ├── routers/
│   │   ├── inference.py  # /predict/, /predict/batch/
│   │   ├── models.py     # /models/, /models/{version}/
│   │   └── health.py     # /health/, /health/models/
│   │
│   └── services/
│       ├── inference_service.py  # Business logic for inference
│       └── model_service.py      # Model management (load, unload, switch)
│
├── tests/
│   ├── ml/              # ML-specific tests
│   │   ├── test_loader.py
│   │   ├── test_predictor.py
│   │   └── test_preproc.py
│   └── api/             # API tests
│       └── test_inference.py
│
└── models/              # Actual ML model files (or download at runtime)
    ├── dinov2/
    │   └── v1.0/
    └── gpt2/
        └── v1.0/
```
The key design: the `ml/` directory isolates all ML-specific code from the API layer. The model registry manages multiple versions (for A/B testing and versioning). The predictor handles batching and inference. Pre/post-processing is separate because it's often the bottleneck and needs independent optimization. The API layer (routers, schemas) is thin — it delegates to the service layer, which uses the ML layer. This structure supports: model versioning (registry), A/B testing (route to different model versions), batch inference (dedicated endpoint with batching logic), and health checks (model status endpoint). The ML code is testable without the API, and the API is testable with mock ML.

## Related
[[dependency-injection]]
[[error-handling-and-exception-handlers]]
[[env-and-config-management]]
[[inference-serving-patterns]]

#status/new