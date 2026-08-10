# Pydantic Models and Validation

## What it is
Pydantic (v2, which FastAPI uses) is a data validation and settings management library based on Python type hints. It validates incoming data (request bodies, query params, environment variables) against type-annotated models, coerces types where possible, and produces detailed error messages when validation fails. Pydantic v2 (released 2023) is a complete rewrite in Rust — dramatically faster than v1 — with a new validation engine, `model_validator` hooks, discriminated unions, `Field` validation, and serialization control. This file covers the v2-specific mechanics that differ from v1, the validation pipeline, and the patterns that separate robust models from fragile ones.

## Why it matters
FastAPI's entire request/response validation is built on Pydantic. Every endpoint that accepts a body or returns a structured response uses Pydantic under the hood. Understanding how validation works — when it runs, how errors are formatted, how to customize it — is essential for building APIs that fail gracefully. In interviews, Pydantic questions test whether you understand the validation order, the difference between `field_validator` and `model_validator`, and how to handle complex validation logic. For your work — ML model inputs/outputs, API request/response shapes, configuration — Pydantic is the tool you'll use constantly.

## Core example

### The validation pipeline — when and how validation runs

```python
from pydantic import BaseModel, Field, field_validator, model_validator
from datetime import datetime

class User(BaseModel):
    id: int
    name: str = Field(..., min_length=1, max_length=100)
    email: str
    age: int | None = None
    created_at: datetime = None
    
    # 1. field_validator — runs on a single field, receives the value
    @field_validator("email")
    @classmethod
    def validate_email(cls, v):
        if "@" not in v:
            raise ValueError("Invalid email")
        return v  # MUST return the (possibly transformed) value
    
    # 2. field_validator with multiple fields
    @field_validator("name", "age", mode="before")
    @classmethod
    def validate_name_and_age(cls, v):
        # mode="before" — runs before type coercion
        # mode="after" (default) — runs after type coercion
        return v
    
    # 3. model_validator — runs after all field validation
    # Can access all validated data, cross-field validation
    @model_validator(mode="after")
    def check_age(self):
        if self.age is not None and self.age < 0:
            raise ValueError("Age must be positive")
        return self  # MUST return self (or a new model instance)
    
    # 4. model_validator mode="before" — runs before any field validation
    # Receives the raw input dict, can transform it
    @model_validator(mode="before")
    @classmethod
    def preprocess(cls, data):
        if isinstance(data, dict):
            # Transform input before validation
            if "full_name" in data:
                data["name"] = data.pop("full_name")
        return data

# Validation order:
# 1. model_validator(mode="before") — transform raw input
# 2. Field type coercion (str → int, etc.)
# 3. field_validator (after type coercion, unless mode="before")
# 4. model_validator(mode="after") — cross-field validation
# 5. Model is built and returned

# If any step fails, validation stops and ValidationError is raised.
# The error contains all failures (not just the first) — Pydantic
# collects all validation errors before raising.
```

### Pydantic v2 vs v1 — the critical differences

```python
# v1: class Config
# v2: model_config = ConfigDict(...)

from pydantic import ConfigDict

class User(BaseModel):
    model_config = ConfigDict(
        extra="forbid",      # Reject unknown fields (v1: extra = "forbid")
        frozen=True,         # Immutable after creation (v1: frozen = True)
        validate_assignment=True,  # Validate on attribute assignment
        from_attributes=True,  # Read from ORM objects (v1: orm_mode = True)
        populate_by_name=True,  # Allow both alias and field name
        str_strip_whitespace=True,  # Auto-stripping strings
        str_to_lower=True,   # Auto-lowercase strings
    )

# v1: validator decorator
# v2: @field_validator and @model_validator

# v1:
# @validator("email")
# def validate_email(cls, v): ...

# v2:
@field_validator("email")
@classmethod
def validate_email(cls, v): ...

# Key v2 changes:
# 1. @classmethod is required on validators (v1 had it implicitly)
# 2. Validators must return the value (v1 too, but now enforced)
# 3. model_validator replaces root_validator
# 4. field_validator replaces validator
# 5. ConfigDict replaces class Config
# 6. from_attributes replaces orm_mode
# 7. Validation is faster (Rust core) — 5-50x faster than v1
# 8. Error messages are more detailed and structured
```

### Field validation — constraints and customization

```python
from pydantic import BaseModel, Field, constr, conint
from typing import Annotated

# Field() with constraints:
class Product(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    price: float = Field(..., gt=0)  # > 0
    quantity: int = Field(default=0, ge=0)  # >= 0
    tags: list[str] = Field(default_factory=list)  # Mutable default
    category: str = Field(default="general")
    sku: str = Field(..., pattern=r"^[A-Z]{3}-\d{4}$")  # Regex
    
    # Field with alias (different name in JSON vs Python)
    product_id: int = Field(..., alias="productId")
    
    # Field with description (appears in OpenAPI docs)
    description: str = Field(default="", description="Product description")

# Constrained types (v2 still supports but Field() is preferred):
# Name = constr(min_length=1, max_length=100)
# PositiveInt = conint(gt=0)
# These create new types with built-in validation.
# But Field() is more flexible and readable — recommended.

# default_factory for mutable defaults:
# IMPORTANT: always use default_factory for list/dict/set defaults.
# Using default=[] has the mutable default trap ([[basics]]).

# Model usage:
p = Product(name="Laptop", price=999.99, productId=123)
print(p.name)  # "Laptop"
print(p.product_id)  # 123 (Python name)
# p.model_dump(by_alias=True) → {"productId": 123, ...} (JSON name)
```

### Discriminated unions — type-safe polymorphism

```python
from pydantic import BaseModel, Field
from typing import Annotated, Union

# A discriminated union lets you have multiple model types in one field,
# with the discriminator field determining which type to validate.

class Cat(BaseModel):
    pet_type: str = "cat"  # Discriminator field
    name: str
    meows: int = True

class Dog(BaseModel):
    pet_type: str = "dog"
    name: str
    barks: int = True

# Annotated with Discriminator tells Pydantic which field to use
# for type discrimination:
from typing import Annotated
Pet = Annotated[
    Union[Cat, Dog],
    Field(discriminator="pet_type")
]

class Owner(BaseModel):
    name: str
    pet: Pet

# Usage:
owner = Owner(name="Alice", pet={"pet_type": "cat", "name": "Whiskers"})
print(type(owner.pet).__name__)  # Cat

owner2 = Owner(name="Bob", pet={"pet_type": "dog", "name": "Rex"})
print(type(owner2.pet).__name__)  # Dog

# Without the discriminator, Pydantic would try each union member
# in order until one validates — which could give wrong results
# if multiple members accept the same data. The discriminator makes
# it deterministic and efficient (only one type is validated).

# This is essential for APIs that accept different payload types
# based on a type field — e.g., different notification types,
# different payment methods, different event types.
```

### Serialization — controlling what goes out

```python
from pydantic import BaseModel, Field, field_serializer

class User(BaseModel):
    id: int
    name: str
    email: str
    password_hash: str = Field(exclude=True)  # Never serialize
    created_at: datetime
    
    # Custom serializer for a field
    @field_serializer("created_at")
    def serialize_dt(self, v: datetime) -> str:
        return v.isoformat()  # Convert datetime to ISO string
    
    # Serializer with mode="json" — only applies to model_dump_json()
    # and FastAPI responses (which use JSON)
    @field_serializer("created_at", mode="json")
    def serialize_dt_json(self, v: datetime) -> str:
        return v.strftime("%Y-%m-%d %H:%M")  # Different format for JSON

# Model serialization methods:
user = User(id=1, name="Alice", email="a@b.com", password_hash="abc", created_at=datetime.now())

user.model_dump()  # Dict — excludes password_hash (exclude=True)
# {"id": 1, "name": "Alice", "email": "a@b.com", "created_at": "..."}

user.model_dump_json()  # JSON string — uses JSON-mode serializers

user.model_dump(exclude={"email"})  # Exclude specific fields
user.model_dump(include={"id", "name"})  # Include only specific fields
user.model_dump(by_alias=True)  # Use alias names
user.model_dump(mode="json")  # JSON-serializable types (datetime → str)

# For FastAPI: the response_model uses model_dump() with the response
# model's field configuration. exclude=True fields are automatically
# excluded from API responses — perfect for sensitive fields.

# Partial updates — Patch models:
class UserUpdate(BaseModel):
    name: str | None = None
    email: str | None = None
    # All fields optional — for PATCH requests
    
    # Only update fields that were provided (not None)
    def create_update_data(self, exclude_unset=True):
        return self.model_dump(exclude_unset=exclude_unset)
        # exclude_unset=True only includes fields explicitly set
        # by the client, not fields with their default values
```

### Validation errors — structure and handling

```python
from pydantic import BaseModel, ValidationError

class User(BaseModel):
    id: int
    email: str

# Validation fails — raises ValidationError
try:
    User(id="not_a_number", email="invalid")
except ValidationError as e:
    # e.errors() — list of error dicts
    for error in e.errors():
        print(error["loc"])    # Field location: ('id',) or ('email',)
        print(error["msg"])     # Human-readable message
        print(error["type"])    # Error type: "int_parsing", "value_error", etc.
        print(error["input"])   # The invalid input value
    
    # e.json() — JSON representation of all errors
    # str(e) — formatted multi-line error string

# FastAPI automatically catches ValidationError and returns 422
# with a structured error body:
# {
#   "detail": [
#     {
#       "loc": ["body", "id"],
#       "msg": "value is not a valid integer",
#       "type": "type_error.integer"
#     }
#   ]
# }

# Custom error messages:
from pydantic import StringConstraints
from typing import Annotated

class User(BaseModel):
    email: str
    
    @field_validator("email")
    @classmethod
    def validate_email(cls, v):
        if "@" not in v:
            # Raise with custom error
            raise ValueError("Email must contain @ symbol")
        return v

# For custom error types, use Pydantic's error types or define
# custom ones with custom error messages. The key: raise ValueError
# (or use assert) in validators — Pydantic wraps it in a proper
# ValidationError with the correct location.
```

### Custom validators — beyond the basics

```python
from pydantic import BaseModel, field_validator, model_validator
import re

class Password(BaseModel):
    value: str
    
    @field_validator("value")
    @classmethod
    def validate_password(cls, v):
        errors = []
        if len(v) < 8:
            errors.append("at least 8 characters")
        if not re.search(r"[A-Z]", v):
            errors.append("at least one uppercase letter")
        if not re.search(r"[a-z]", v):
            errors.append("at least one lowercase letter")
        if not re.search(r"\d", v):
            errors.append("at least one digit")
        if errors:
            raise ValueError(f"Password must have: {', '.join(errors)}")
        return v

# Cross-field validation with model_validator:
class Booking(BaseModel):
    check_in: date
    check_out: date
    
    @model_validator(mode="after")
    def check_dates(self):
        if self.check_out <= self.check_in:
            raise ValueError("Check-out must be after check-in")
        return self

# Before-validation transformation:
class User(BaseModel):
    phone: str
    
    @model_validator(mode="before")
    @classmethod
    def normalize_phone(cls, data):
        if isinstance(data, dict) and "phone" in data:
            # Remove all non-digit characters
            data["phone"] = re.sub(r"\D", "", data["phone"])
        return data
```

## Common mistakes / gotchas

- **Mutable default values** — `tags: list[str] = []` has the mutable default trap. Always use `default_factory=list`: `tags: list[str] = Field(default_factory=list)`.
- **Validators not returning the value** — field validators must return the (possibly transformed) value. If you don't return it, the field becomes `None`. Always `return v` at the end.
- **`mode="before"` vs `mode="after"`** — `mode="before"` validators receive the raw input (before type coercion). `mode="after"` receives the coerced value. For string normalization, use `mode="before"`. For format validation, use `mode="after"`.
- **`@classmethod` required in v2** — v2 requires `@classmethod` on validators. Forgetting it causes a confusing error. The first argument is the class (cls), not the instance.
- **model_validator returning wrong value** — `mode="after"` validators must return `self` (or a new model instance). Returning None or a dict breaks the model. `mode="before"` must return the input dict (or a transformed dict).
- **extra="forbid" breaking API evolution** — if you add a new field to a model and old clients send requests without it, `extra="forbid"` doesn't affect missing fields (it affects EXTRA fields). But if clients send fields you removed, they get 422. Use `extra="ignore"` for backward-compatible APIs.
- **`exclude_unset=True` vs `exclude_defaults=True`** — `exclude_unset` only includes fields explicitly set by the user. `exclude_defaults` excludes fields with their default values. For PATCH requests (partial updates), use `exclude_unset=True` — you only want to update fields the client explicitly sent.
- **Pydantic v1 vs v2 migration** — if you're reading v1 code or tutorials, the syntax differs significantly: `class Config` → `model_config`, `validator` → `field_validator`/`model_validator`, `orm_mode` → `from_attributes`, `root_validator` → `model_validator`. Don't mix v1 and v2 patterns.

## Practice

> [!question]- Q1. You have an API endpoint that accepts a date range. The client sends `start_date` and `end_date` as strings in "YYYY-MM-DD" format. Design a Pydantic model that validates the format, ensures end_date >= start_date, and converts the strings to date objects.
**Answer:**
```python
from pydantic import BaseModel, field_validator, model_validator
from datetime import date

class DateRange(BaseModel):
    start_date: str
    end_date: str
    
    @field_validator("start_date", "end_date")
    @classmethod
    def validate_format(cls, v):
        try:
            date.fromisoformat(v)
        except ValueError:
            raise ValueError("Date must be in YYYY-MM-DD format")
        return v
    
    @model_validator(mode="after")
    def check_order(self):
        start = date.fromisoformat(self.start_date)
        end = date.fromisoformat(self.end_date)
        if end < start:
            raise ValueError("end_date must be >= start_date")
        return self
    
    # Convenience properties for the validated dates
    @property
    def start(self) -> date:
        return date.fromisoformat(self.start_date)
    
    @property
    def end(self) -> date:
        return date.fromisoformat(self.end_date)
```
The field validator checks the format of each date string. The model validator checks the cross-field constraint (end >= start). The convenience properties provide typed access to the parsed dates. Alternatively, you could parse the dates in the field validator and store them as `date` objects directly — but then the model's type hints wouldn't match the stored types. The cleaner approach: use `date` as the field type with a `before` validator that parses:
```python
start_date: date = Field(...)
end_date: date = Field(...)

@field_validator("start_date", "end_date", mode="before")
@classmethod
def parse_date(cls, v):
    if isinstance(v, str):
        return date.fromisoformat(v)
    return v
```
This way, the model stores `date` objects natively, and the type hints are accurate.

> [!question]- Q2. Design a Pydantic model for a user registration endpoint that: (1) requires email and password, (2) validates password strength, (3) hashes the password before storing, (4) never returns the password in API responses, (5) accepts both camelCase and snake_case input.
**Answer:**
```python
from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Annotated
import hashlib
import re

PasswordStr = Annotated[str, Field(min_length=8)]

class UserCreate(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,  # Accept both email and emailAddress
        from_attributes=True,
    )
    
    email: str
    email_address: str | None = None  # Alias alternative
    password: Annotated[str, Field(min_length=8, write_only=True)]
    
    @field_validator("email")
    @classmethod
    def validate_email(cls, v):
        if "@" not in v or "." not in v.split("@")[-1]:
            raise ValueError("Invalid email format")
        return v.lower()
    
    @field_validator("password")
    @classmethod
    def validate_password(cls, v):
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain an uppercase letter")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain a digit")
        return v
    
    @model_validator(mode="after")
    def hash_password(self):
        # Hash the password — in production, use bcrypt/argon2
        self._password_hash = hashlib.sha256(self.password.encode()).hexdigest()
        return self
    
    # write_only=True ensures password is excluded from responses
    # But for extra safety, also exclude it explicitly:
    def model_dump(self, **kwargs):
        data = super().model_dump(**kwargs)
        data.pop("password", None)
        return data
    
    @property
    def password_hash(self) -> str:
        return self._password_hash
```
The `write_only=True` field excludes the password from serialization. The field validator enforces password strength. The model validator hashes the password after validation. `populate_by_name=True` allows both `email` and `emailAddress` in the input. For production, use `passlib` with bcrypt instead of SHA-256. The key design: validation, transformation, and security concerns are all handled in the model — the endpoint receives a validated, hashed user object and can directly pass it to the database layer.

> [!question]- Q3. You have a polymorphic API endpoint that accepts different notification types (email, SMS, push). Each type has different required fields. Design the model using discriminated unions and show how FastAPI uses it in an endpoint.
**Answer:**
```python
from pydantic import BaseModel, Field
from typing import Annotated, Union

class EmailNotification(BaseModel):
    type: str = "email"
    to: str
    subject: str
    body: str
    cc: list[str] = []

class SMSNotification(BaseModel):
    type: str = "sms"
    to: str  # Phone number
    message: str
    sender: str = "NOTIFY"

class PushNotification(BaseModel):
    type: str = "push"
    device_token: str
    title: str
    body: str
    click_action: str | None = None

Notification = Annotated[
    Union[EmailNotification, SMSNotification, PushNotification],
    Field(discriminator="type")
]

@app.post("/notify/", status_code=202)
async def send_notification(notification: Notification):
    # FastAPI validates based on the "type" field
    # notification is already the correct subtype
    match notification.type:
        case "email":
            send_email(notification.to, notification.subject, notification.body)
        case "sms":
            send_sms(notification.to, notification.message)
        case "push":
            send_push(notification.device_token, notification.title, notification.body)
    return {"status": "sent", "type": notification.type}
```
The discriminated union lets the endpoint accept a single `Notification` parameter that can be any of the three types. FastAPI validates based on the `type` field and constructs the appropriate subtype. The endpoint uses pattern matching (or if/elif) to handle each type. The OpenAPI docs show all three notification types with their respective fields. This is the cleanest way to handle polymorphic input in FastAPI — single endpoint, type-safe handling, auto-generated docs.

> [!question]- Q4. Explain the difference between `field_validator`, `model_validator`, and `Field()` constraints. When would you use each for validating a user's age field?
**Answer:** `Field()` constraints are declarative — `age: int = Field(..., ge=0, le=150)`. They're simple, fast, and appear in OpenAPI docs. Use for basic constraints (range, length, pattern). `field_validator` is imperative — `@field_validator("age")` with custom Python logic. Use for validation that can't be expressed as a constraint (e.g., "age must be even" or "age must be a prime number"). `model_validator` is for cross-field validation — e.g., "age must be less than parent's age" or "age + experience_years <= 80". For age specifically: use `Field()` for range (ge=0, le=150), use `field_validator` for custom rules (e.g., "must be integer, not float"), use `model_validator` only if age depends on another field. The general rule: simplest tool first — Field constraints for simple rules, field_validator for single-field custom logic, model_validator for cross-field logic.

> [!question]- Q5. A FastAPI endpoint with a Pydantic model returns 422 for a valid-looking JSON input. The error says "value is not a valid integer" for a field that's clearly an integer in the JSON. What are the possible causes, and how do you diagnose each?
**Answer:** Possible causes: (1) **String instead of number** — the JSON has `"age": "25"` (quoted string) instead of `"age": 25` (number). JSON strings are not automatically coerced to integers in Pydantic v2 (v1 was more lenient). Diagnosis: check the raw JSON — look for quotes around the number. (2) **Float instead of integer** — the JSON has `"age": 25.0` (float) and the model expects `int`. Pydantic v2 doesn't coerce float to int by default. Diagnosis: check if the number has a decimal point. (3) **Field location error** — the error says `loc: ["body", "user", "age"]` meaning the field is nested inside a `user` object, but you're sending it at the top level. Diagnosis: check the error location — it tells you the exact path to the field. (4) **Extra fields forbidden** — the model has `extra="forbid"` and the JSON has a typo'd field name that looks like a real field. Diagnosis: check the error for "extra fields not permitted" and compare field names. (5) **Alias mismatch** — the field has `alias="userId"` but the JSON uses `user_id`. Diagnosis: check the model for `Field(alias=...)` and match the JSON key exactly. The 422 response body contains all this information — read the `loc`, `msg`, and `type` fields for each error. They tell you exactly what's wrong.

## Related
[[routing-and-params]]
[[typing-and-type-hints]]
[[error-handling-and-exception-handlers]]
[[request-response-lifecycle]]

#status/new