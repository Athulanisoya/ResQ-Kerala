# Historical code explanation — ResQ Week 1 authentication contribution

This guide records the independent ResQ authentication contribution inspected on **6 October 2026**. Its standalone source root is referred to as `<authentication-source-root>`. Users register, sign in, view their account, verify their role permissions, and sign out.

**Historical snapshot:** the file paths, line numbers, React frontend, standalone ports and limited feature scope below describe that earlier contribution, not the integrated HTMX application. Personal labels and example identifiers have been renamed to ResQ for consistency, so quoted examples are adapted rather than exact copies of the old source. Use the [current README](../README.md) and [integration record](INTEGRATION.md) for the delivered application and its setup.

The backend is **FastAPI + SQLAlchemy + PostgreSQL**. The browser interface is **React**, built and served locally with **Vite**. Passwords use **Argon2 hashing** through pwdlib. A signed **JWT** identifies a **persisted database session**, so authentication checks are performed on the server on every protected request.

## How to read this guide

Start with the feature and request-flow explanations. Then read the numbered tables in this order: settings/database/models → schemas → password/JWT/permission helpers → services → routes/application startup → frontend → setup scripts → tests.

Each table contains the **physical source line number**, the **source code with adapted ResQ labels**, and an explanation of its effect. Every nonblank source line in the 41 included source/configuration files has a row, including imports, comments, JSX, CSS, closing delimiters, tests, and small package initializers. Blank lines are visual separators; they execute nothing and are accounted for globally rather than repeated in the tables. A single physical line can contain several statements or JSX elements; its explanation covers them together.

The guide describes `.env.example`, never the private `.env` or generated credentials. Compiled files in `frontend/dist`, dependency directories, caches, logs, generated runtime files, and the generated npm lockfile are not handwritten application logic. README and task notes are summarized as documentation.

Line numbers belong to this inspected source version. Later code edits can change them.

- [Implemented features](#implemented-features)
- [Architecture and data model](#architecture-and-data-model)
- [End-to-end request flows](#end-to-end-request-flows)
- [API contract and permission matrix](#api-contract-and-permission-matrix)
- [Syntax and library glossary](#syntax-and-library-glossary)
- [Backend line-by-line tables](#backend-code)
- [Frontend line-by-line tables](#frontend-code)
- [Scripts, configuration, and package tables](#supporting-scripts-and-configuration)
- [Tests and assertions](#tests)
- [Source-verification record](#source-verification-record)

## Implemented features

| Feature | What the code actually does | Main implementation |
| --- | --- | --- |
| Citizen registration | Accepts name, email, and password; creates a citizen and signs them in immediately. | `schemas/auth.py`, `services/auth_service.py`, `routers/auth.py` |
| Input validation | Requires a 3–100 character normalized name, valid email up to 254 characters, and a strict string password of 10–128 characters; rejects unknown fields. | `schemas/auth.py` |
| Identity normalization | Trims name/email and lowercases email, so differently cased addresses match the same account. | `schemas/auth.py`, `services/auth_service.py` |
| Significant password whitespace | Keeps spaces in passwords rather than silently changing the user's chosen password. | `schemas/auth.py`, `Login.jsx` |
| Duplicate-account protection | Checks normalized email first, then relies on database-enforced uniqueness through a unique index; returns HTTP 409 on a caught registration integrity conflict. | `models/user.py`, `services/auth_service.py` |
| Password hashing | Stores an encoded Argon2 hash with a salt, rather than a plaintext password. | `utils/security.py` |
| Login | Checks the password and active account status; returns a new JWT and session for each successful login. | `services/auth_service.py` |
| Generic failed-login response | Missing email, incorrect password, and inactive account get the same 401 message; a missing email still performs dummy hash verification. | `services/auth_service.py`, `utils/security.py` |
| Signed bearer tokens | Signs HS256 JWTs with subject, session ID, issue/expiry time, issuer, and audience. Default expiry is 30 minutes. | `utils/jwt.py`, `config.py` |
| Persisted-session checks | Requires the referenced session to exist, remain unrevoked/unexpired, and belong to the token's user; also checks the account is active. | `utils/permissions.py` |
| Current-session logout | Persists a revocation timestamp for the supplied session; other sessions for the same account stay active. | `services/auth_service.py` |
| Current account | Returns only public profile fields through an authenticated endpoint. | `routers/users.py`, `UserResponse` |
| Role authorization | Allows citizen, admin, and response_team accounts into their own role endpoint; reads the current role from the database each request. | `utils/permissions.py`, `routers/workspaces.py` |
| Privileged-role provisioning | Local setup seeds demo admin/team users. Public registration rejects role and team_id fields and forces citizen. | `seed.py`, `RegisterRequest` |
| Browser session restoration | Retains the token/profile in tab-scoped sessionStorage through reload, then verifies the current profile with `/api/users/me`. | `api.js`, `App.jsx` |
| Expiration handling | An authenticated protected request returning 401 clears saved session state and announces an expiration event to App. | `api.js`, `App.jsx` |
| Role-specific navigation | Shows the user's own workspace and account view; the workspace makes three real API requests to display allowed/denied results. | `App.jsx` |
| Responsive and accessible UI elements | Provides labeled forms, focus outlines, loading/error states, semantic tables, a skip link, responsive layouts, and reduced-motion CSS. | `Login.jsx`, `App.jsx`, `styles.css` |
| Database isolation | Stores accounts and sessions in a separate PostgreSQL schema named resq_week1 by default. | `config.py`, `database/connection.py` |
| Database health | Executes SELECT 1 and reports connected/unavailable status. | `main.py` |
| Local lifecycle scripts | Install dependencies, configure/seeding, start or reuse module services, record process ownership, and stop tracked module services. | `scripts/` |
| Focused automated tests | Contains 27 collected test cases for authentication, input validation, session lifecycle, and role access using isolated SQLite. | `backend/tests/test_auth.py` |

The role workspaces return a title and authorization message. This code does not implement incident reporting, rescue dispatch, relief operations, shelters, chatbots, or AI recommendations. The account view displays data and has no profile-editing form.

## Architecture and data model

```mermaid
flowchart TD
    Browser[Browser: React UI on port 5175] --> Client[api.js: JSON requests and bearer header]
    Client --> Proxy[Vite proxy for /api and /health]
    Proxy --> API[FastAPI on port 8012]
    API --> Schemas[Pydantic: validate request data]
    API --> Permissions[Dependencies: authentication and role checks]
    API --> Service[Auth service: register, login, logout]
    Service --> Security[Argon2 and signed JWT helpers]
    Service --> DB[(PostgreSQL: resq_week1)]
    Permissions --> Security
    Permissions --> DB
    DB --> Users[users]
    DB --> Sessions[token_sessions]
```

The frontend is responsible for forms, state, presentation, and requesting data. The API is responsible for validating inputs, storing records, checking passwords/tokens, and deciding access. Hiding a navigation link is a display choice; calling an unauthorized endpoint directly still receives a server-side refusal.

| Layer | Responsibility | Representative file |
| --- | --- | --- |
| Settings | Load validated database/token/browser-origin settings. | `backend/config.py` |
| Database | Create the engine/session factory and initialize missing tables. | `backend/database/connection.py` |
| Models | Describe stored account/session columns and constraints. | `backend/models/user.py` |
| Schemas | Describe accepted JSON and safe returned fields. | `backend/schemas/auth.py` |
| Utilities | Hash passwords, sign/decode JWTs, identify users, and check roles. | `backend/utils/` |
| Service | Coordinate queries, hashing, account creation, and commits. | `backend/services/auth_service.py` |
| Routers | Map HTTP paths/methods to schemas, dependencies, and services. | `backend/routers/` |
| App | Compose routes, middleware, lifecycle, and health. | `backend/main.py` |
| Frontend | Render forms/account/workspace UI and coordinate browser sessions. | `frontend/src/` |
| Scripts | Prepare and run the standalone local demonstration. | `scripts/` |

There are two database tables, with a **one-account-to-many-sessions** relationship:

```mermaid
erDiagram
    USERS ||--o{ TOKEN_SESSIONS : has
    USERS {
        int id PK
        string full_name
        string email UK
        string password_hash
        string role
        int team_id "nullable compatibility field"
        boolean active
        datetime created_at
    }
    TOKEN_SESSIONS {
        string id PK "UUID string, also JWT sid"
        int user_id FK
        datetime created_at
        datetime expires_at
        datetime revoked_at "null until revoked"
    }
```

`team_id` is an optional compatibility field, not a complete team-membership implementation. These models do not define a teams table. `TokenSession` is a login-session record, while SQLAlchemy's `Session` is a database unit of work; the same word refers to different things here.

## End-to-end request flows

### 1. Setup and startup

1. `setup.ps1` creates/reuses a Python environment, installs backend/frontend dependencies when requested, and creates `.runtime/tmp`.
2. `scripts.configure` keeps an existing `.env`, or uses the parent's database URL and generates this module's own signing secret when creating one.
3. `backend.seed` initializes the separate schema/tables and inserts missing demo accounts for the three roles. The generated local password record is kept under `.runtime`.
4. Setup saves the selected Python executable in `.runtime/setup.json`.
5. `start.ps1` verifies existing listeners or starts Uvicorn on 8012 and Vite on 5175, waits for HTTP readiness, and records matching processes.
6. Backend imports register model metadata and route handlers. FastAPI's lifespan then initializes the database before serving requests.
7. A browser requests the frontend HTML, which loads `main.jsx`; React mounts `App` in the `root` element.

The scripts use an already running PostgreSQL instance. Starting/stopping this module does not start/stop that shared database service.

### 2. Register a citizen

1. `Login.jsx` switches to register mode and shows full name, email, and password fields.
2. On submit it prevents a normal page reload, clears the old error, and marks the form busy.
3. It normalizes name/email, preserves the password exactly, and calls `api('/api/auth/register', { method: 'POST', body: ... })`.
4. `api.js` serializes the body as JSON. Vite forwards the relative `/api` URL to FastAPI in the local development/preview configuration.
5. FastAPI validates the JSON as `RegisterRequest`. Extra privilege fields or invalid data return 422 before the service creates an account.
6. `auth_service.register` checks for an existing normalized email. It hashes the password, constructs a citizen `User`, and flushes the insert to obtain its ID.
7. `auth_result` calls `create_session_token`, which stages a `TokenSession` with a UUID and expiry, then signs the JWT.
8. `auth_result` commits the account/session transaction and returns an AuthResponse with token and safe user fields; the registration route serializes it with HTTP 201.
9. The frontend calls App's `login(session)`, saves the returned session, and asks `/api/users/me` to verify the profile using the new token.
10. After verification, App sets its `user`, opens the workspace, and permission checks run. Registration already signs the new citizen in.

### 3. Log in

Login takes the same browser-to-router path, but sends only email/password to `/api/auth/login`. The service looks up the normalized email, verifies its real hash or a dummy hash, and requires an active account. Successful login creates **a new saved session**, commits it, and returns HTTP 200 with a JWT and safe profile.

The dummy verification reduces a simple difference in password-hashing work for unknown emails. It does not establish a guarantee that every login failure has identical timing.

### 4. Authenticate a protected request and check a role

```mermaid
sequenceDiagram
    participant UI as React api.js
    participant Route as Protected endpoint
    participant Auth as get_principal
    participant JWT as decode_session_token
    participant DB as Database
    UI->>Route: GET with Authorization: Bearer token
    Route->>Auth: FastAPI dependency injection
    Auth->>JWT: Verify signature, required claims, issuer, audience, expiry
    JWT-->>Auth: Verified sub and sid
    Auth->>DB: Load TokenSession by sid
    Auth->>Auth: Check existence, revocation, expiry, user ownership
    Auth->>DB: Load current User
    Auth->>Auth: Require existing active account
    Auth-->>Route: Principal and current User
    Route->>Route: require_roles checks current database role
    Route-->>UI: 200 allowed, 401 invalid authentication, or 403 wrong role
```

The JWT holds `sub` (user ID) and `sid` (saved session ID), along with time/issuer/audience claims. It **does not hold the role**. Consequently, changing a user's role or active flag in the database affects their next protected request without issuing a replacement token.

The browser's saved user object is used to coordinate UI, but it does not decide backend permission. Session restoration and accepted sign-in fetch a fresh profile, and every protected endpoint authenticates on the server.

### 5. Display workspace and account

`PermissionsWorkspace` concurrently requests all three role endpoints. For the current definitions, its own role returns 200 and the other two return 403. It displays the successful response's title/message and the three access results. “Check access again” increments a state counter, which reruns the effect; cleanup aborts obsolete requests.

The account view renders the verified full name, email, role, and ID, plus team ID when truthy. Navigation changes React's local `view` state rather than navigating separate browser routes.

### 6. Reload, expiration, and logout

On reload, App detects a saved tab session and shows a verification state while fetching `/api/users/me`. A verified profile restores the authenticated screen. A missing/invalid session leads to sign-in; a connectivity failure shows a retry screen without treating every network failure as an expired token.

There is no refresh-token endpoint or automatic renewal. Expiry is noticed when the API validates a request; the UI does not run a timer that logs the user out at the exact expiry instant.

Logout calls `/api/auth/logout` with the current bearer token. `get_principal` authenticates it, the service sets that session's `revoked_at`, and the API returns 204 with no body. The browser then clears its saved session/user. If the server request fails, App still clears the device's state and explicitly says server revocation could not be confirmed. An independent second login session is not revoked by logging out the first.

## API contract and permission matrix

| Method | Endpoint | Who can call it successfully | Success |
| --- | --- | --- | --- |
| POST | `/api/auth/register` | Public, valid new citizen registration | 201 + AuthResponse |
| POST | `/api/auth/login` | Public, valid active-account credentials | 200 + AuthResponse |
| POST | `/api/auth/logout` | Authenticated current session | 204, empty body |
| GET | `/api/users/me` | Any authenticated active account | 200 + UserResponse |
| GET | `/api/workspaces/citizen` | Citizen only | 200 + role/title/message |
| GET | `/api/workspaces/admin` | Admin only | 200 + role/title/message |
| GET | `/api/workspaces/response-team` | Response-team only | 200 + role/title/message |
| GET | `/health` | Public | 200 when database probe succeeds; 503 otherwise |

FastAPI also provides interactive API documentation at `/docs` and the generated OpenAPI schema at `/openapi.json` through its defaults.

| Signed-in role | Citizen workspace | Admin workspace | Response-team workspace | My account |
| --- | --- | --- | --- | --- |
| citizen | 200 | 403 | 403 | 200 |
| admin | 403 | 200 | 403 | 200 |
| response_team | 403 | 403 | 200 | 200 |
| No valid active session | 401 | 401 | 401 | 401 |

In this implementation, admin is one of the three allowed roles, not an automatic bypass for every workspace.

An example registration body uses synthetic learning values:

```json
{
  "full_name": "Sample Citizen",
  "email": "sample@example.com",
  "password": "Synthetic-learning-password!"
}
```

Successful registration/login has this shape; the token shown is a placeholder, not a usable credential:

```json
{
  "access_token": "<signed JWT returned by the API>",
  "token_type": "bearer",
  "user": {
    "id": 1,
    "full_name": "Sample Citizen",
    "email": "sample@example.com",
    "role": "citizen",
    "team_id": null
  }
}
```

Protected requests supply `Authorization: Bearer <access_token>`. The response schema excludes password and password_hash. JWT signing proves integrity/authenticity to this server; JWT payloads are not encrypted by this code and should not be treated as private containers.

| Status | Meaning in this app |
| --- | --- |
| 200 | Successful login, profile, workspace, or healthy database probe. |
| 201 | Account and its initial session were created. |
| 204 | Current-session logout succeeded and has no JSON body. |
| 401 | Login credentials failed, or protected authentication is missing/invalid/expired/revoked/inactive. |
| 403 | Authentication succeeded but the current role is not allowed. |
| 409 | Registration found an existing email or caught an integrity conflict. |
| 422 | Request validation failed, including extra registration privilege fields. |
| 503 | The health probe failed or an unhandled SQLAlchemy database error occurred. |

## Syntax and library glossary

| Concept | Meaning in this code |
| --- | --- |
| Relative Python import, such as `from ..models import User` | Import from a neighboring package within backend; two dots go to the parent package. |
| Type annotation, such as `db: Session` or `-> User` | Describes the intended type; FastAPI/Pydantic also use annotations to wire dependencies and validation. |
| Decorator, such as `@router.post(...)` | Runs when the function is defined to register or wrap it; it is not a function call made manually by the browser. |
| `Depends(...)` | FastAPI resolves another callable before the endpoint and supplies its result; nested dependencies build the authentication pipeline. |
| Pydantic schema | A model for validation/serialization of API/configuration data; it is separate from the SQLAlchemy database table model. |
| SQLAlchemy ORM | Maps Python User/TokenSession objects to rows and generates SQL queries/inserts/updates. |
| `Mapped[...]` and `mapped_column(...)` | Declare an ORM attribute and its database-column behavior/type. |
| `select(User).where(...)` | Build a SELECT query; `db.scalar(...)` executes it and returns the first selected entity or None. |
| `db.add`, `flush`, `commit`, `rollback` | Stage an object, send pending changes without finalizing, finalize a transaction, and undo a failed/uncommitted transaction. |
| `with ...` | A context manager handles resource entry/cleanup, such as closing a database session. |
| `yield` | Temporarily provides a resource/control; code after it handles teardown in dependencies/lifespan/fixtures. |
| `async` / `await` | Cooperatively wait for asynchronous work; this app also uses synchronous ORM/service functions for database handling. |
| `try` / `except` / `finally` | Perform work, handle a specified failure, and run cleanup regardless of success/failure. |
| `*roles` | Collect positional role arguments into a tuple for the permission factory. |
| `**engine_options` / `**data` | Expand a Python dictionary into named function/constructor arguments. |
| Closure | The inner role-check function retains the roles supplied to the outer require_roles call. |
| `SecretStr` | Mask a value in ordinary representations; retrieving its raw secret deliberately is still possible. |
| JSX | React's markup-like JavaScript syntax; `{...}` evaluates JavaScript values inside UI markup. |
| Component and props | A function returning React UI and the values passed to it, such as `Account({ user })`. |
| `useState` | Store component state and provide a setter that schedules a rerender. |
| `useEffect` | Coordinate work after rendering; its dependency array controls reruns and its returned function cleans up listeners/requests. |
| Controlled input | React state supplies the input's value, and onChange updates that state. |
| `.map(...)` and keys | Transform a list into requests or repeated UI; React's key identifies a rendered list item. |
| Promise / `Promise.all` | Represent pending async results; Promise.all collects the three concurrent workspace checks in input order. |
| `AbortController` | Supply a cancellation signal to fetch and abort obsolete component requests during cleanup. |
| `...object` | JavaScript object spread copies fields, used for request options, credentials, sessions, and result records. |
| `?.` and `condition ? a : b` | Safely access possibly missing values and choose conditional values/UI. |
| `sessionStorage` | Browser storage associated with a page session/tab, surviving reload and accessible to JavaScript. It is not a server authentication source. |
| CSS selector and declarations | Choose elements and apply styles; classes are connected through JSX className. |
| CSS media query | Apply layout/style overrides based on screen width or a user preference such as reduced motion. |
| FastAPI | Web API framework providing routes, dependencies, request validation integration, response serialization, and docs. |
| Uvicorn | ASGI server that runs backend.main:app locally. |
| psycopg | PostgreSQL driver selected by the configured SQLAlchemy URL. |
| PyJWT | Encode/sign JWTs and decode/verify their signatures and configured claims. |
| pwdlib | High-level password hash/verification interface; the installed recommended hasher is Argon2. |
| Vite | Frontend development server, JSX build tooling, proxy, and build-preview server. |
| React / ReactDOM | Build component UI and mount/render it in the browser. |
| lucide-react | SVG icon components used throughout the interface. |
| pytest / TestClient / httpx | Discover/assert test cases and make in-process API test requests. |

## Implementation boundaries

The source contains no password-reset flow, email-ownership verification, multi-factor authentication, login-rate limiting, refresh tokens, all-sessions logout, or expired-session cleanup job. Schema initialization uses create_all rather than migrations. Vite's local proxy configuration does not establish a hosted deployment; a deployed frontend needs the appropriate API routing.

The existing UI contains useful accessibility features, but this explanation is not a complete accessibility audit. The SQLite tests verify the covered API/ORM behaviors rather than PostgreSQL deployment or browser rendering. Detailed file-level explanations below state other practical boundaries where they matter.

## Backend code

### `backend/config.py`

Loads and validates the configuration used by the API, database, and JWT helpers. The actual private .env is deliberately not reproduced.

| Line | Code | Explanation |
| --- | --- | --- |
| 1 | <code>from functools import lru_cache</code> | Imports a decorator that caches a function result, so configuration is not repeatedly loaded. |
| 2 | <code>from pathlib import Path</code> | Imports the object-oriented filesystem path class. |
| 4 | <code>from pydantic import Field, SecretStr, field_validator, model_validator</code> | Imports field constraints, a masked secret type, and Pydantic validation decorators. |
| 5 | <code>from pydantic_settings import BaseSettings, SettingsConfigDict</code> | Imports environment-based settings and their configuration object. |
| 8 | <code>WORKSPACE_ROOT = Path(__file__).resolve().parents[1]</code> | Resolves this file's absolute path and selects the project directory: config.py is inside backend, so parents[1] is the standalone project root. |
| 11 | <code>class Settings(BaseSettings):</code> | Defines the settings object; BaseSettings can obtain values from environment variables and the configured .env file. |
| 12 | <code>model_config = SettingsConfigDict(</code> | Begins the settings-loading configuration. |
| 13 | <code>env_file=WORKSPACE_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"</code> | Reads the project .env as UTF-8 and ignores extra configuration keys rather than failing on unrelated settings. Process environment variables take precedence over .env values. |
| 14 | <code>)</code> | Closes the multiline function call or constructor begun above. |
| 16 | <code>database_url: str</code> | Requires the database connection URL; there is no default here. |
| 17 | <code>jwt_secret: SecretStr</code> | Requires the signing secret and wraps it in SecretStr, which masks ordinary representations. It is still accessible deliberately through get_secret_value(). |
| 18 | <code>jwt_expire_minutes: int = Field(default=30, ge=5, le=1440)</code> | Defaults session lifetime to 30 minutes; valid configured values are integers from 5 through 1440 minutes. |
| 19 | <code>cors_origins: str = "http://localhost:5175,http://127.0.0.1:5175"</code> | Provides two allowed browser origins for the local frontend. localhost and 127.0.0.1 count as different origins. |
| 20 | <code>allow_sqlite_for_tests: bool = False</code> | Disallows SQLite unless the test-only configuration explicitly enables it. |
| 21 | <code>app_version: str = "1.0.0-resq-week1"</code> | Sets the API's default version label. |
| 22 | <code>database_schema: str = Field(default="resq_week1", pattern=r"^[a-z][a-z0-9_]{0,62}$")</code> | Defaults PostgreSQL isolation to the resq_week1 schema. The regular expression restricts its name to 1-63 lowercase letters, digits, or underscores, beginning with a lowercase letter. |
| 24 | <code>@field_validator("jwt_secret")</code> | Registers the following validator for the jwt_secret setting. |
| 25 | <code>@classmethod</code> | Makes the validator a class method; Pydantic passes the class as cls. |
| 26 | <code>def validate_secret(cls, value: SecretStr) -&gt; SecretStr:</code> | Accepts and returns a SecretStr, preserving the masked representation. |
| 27 | <code>if len(value.get_secret_value()) &lt; 32:</code> | Checks the actual secret's character count; this is a length check, not an entropy measurement. |
| 28 | <code>raise ValueError("JWT_SECRET must contain at least 32 characters")</code> | Rejects settings when the signing secret is shorter than 32 characters. |
| 29 | <code>return value</code> | Returns the validated secret unchanged. |
| 31 | <code>@model_validator(mode="after")</code> | Runs the following validator after all settings fields have been parsed. |
| 32 | <code>def validate_database(self) -&gt; "Settings":</code> | Defines whole-object database validation and returns the same settings instance on success. |
| 33 | <code>if self.database_url.startswith("sqlite"):</code> | Recognizes SQLite URLs by their prefix. |
| 34 | <code>if not self.allow_sqlite_for_tests:</code> | Checks whether the explicit test override is absent. |
| 35 | <code>raise ValueError("SQLite is restricted to tests; set ALLOW_SQLITE_FOR_TESTS=true")</code> | Rejects SQLite when its test override has not been enabled. |
| 36 | <code>elif not self.database_url.startswith("postgresql+psycopg://"):</code> | For non-SQLite URLs, requires the SQLAlchemy PostgreSQL URL prefix that selects the psycopg driver. |
| 37 | <code>raise ValueError("DATABASE_URL must use postgresql+psycopg://")</code> | Rejects unsupported database URL prefixes. This check does not attempt a database connection. |
| 38 | <code>return self</code> | Returns the validated settings object. |
| 40 | <code>@property</code> | Exposes the following method as a computed attribute. |
| 41 | <code>def allowed_origins(self) -&gt; list[str]:</code> | Defines the allowed_origins list property used by CORS middleware. |
| 42 | <code>return [value.strip() for value in self.cors_origins.split(",") if value.strip()]</code> | Splits the comma-separated origin string, trims each item, and drops empty entries. |
| 45 | <code>@lru_cache</code> | Caches the returned settings object. Because this function has no arguments, normal calls reuse one cached object per Python process. |
| 46 | <code>def get_settings() -&gt; Settings:</code> | Defines the common configuration accessor used throughout the backend. |
| 47 | <code>return Settings()</code> | Constructs Settings on the first call; missing or invalid required configuration fails at this point. |

### `backend/database/connection.py`

Creates SQLAlchemy's model base, shared engine, request-scoped sessions, and initial tables. Production uses PostgreSQL; SQLite settings support isolated tests.

| Line | Code | Explanation |
| --- | --- | --- |
| 1 | <code>from collections.abc import Generator</code> | Imports the type annotation for a generator that yields resources. |
| 3 | <code>from sqlalchemy import MetaData, create_engine, event</code> | Imports table metadata, engine creation, and connection-event hooks. |
| 4 | <code>from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker</code> | Imports the declarative ORM base, session type, and session factory builder. |
| 5 | <code>from sqlalchemy.pool import StaticPool</code> | Imports a pool that reuses a single connection, needed for a shared in-memory SQLite database. |
| 6 | <code>from sqlalchemy.schema import CreateSchema</code> | Imports SQLAlchemy's schema-creation statement for PostgreSQL. |
| 8 | <code>from ..config import get_settings</code> | Imports the project's cached settings accessor. |
| 11 | <code>settings = get_settings()</code> | Loads configuration before defining metadata and the engine. |
| 14 | <code>class Base(DeclarativeBase):</code> | Defines the base class inherited by all ORM table models. |
| 15 | <code>metadata = MetaData(schema=None if settings.database_url.startswith("sqlite") else settings.database_schema)</code> | Uses no schema for SQLite and the configured schema for PostgreSQL. Tables derived from Base inherit this metadata namespace. |
| 18 | <code>settings = get_settings()</code> | Calls get_settings again; caching means this reuses the same configuration. This second assignment is redundant. |
| 19 | <code>engine_options: dict = {"pool_pre_ping": True}</code> | Starts engine options with pool_pre_ping, which checks a pooled connection before handing it out and can replace stale connections. |
| 20 | <code>if settings.database_url.startswith("sqlite"):</code> | Begins SQLite-specific engine configuration. |
| 21 | <code>engine_options["connect_args"] = {"check_same_thread": False}</code> | Allows a SQLite connection to be used across the threads involved in API testing; it is not a general concurrency solution. |
| 22 | <code>if settings.database_url in {"sqlite://", "sqlite:///:memory:", "sqlite+pysqlite:///:memory:"}:</code> | Detects the listed memory-only SQLite URL forms. |
| 23 | <code>engine_options["poolclass"] = StaticPool</code> | Reuses one connection so the in-memory database survives across the sessions sharing this engine. |
| 25 | <code>engine = create_engine(settings.database_url, **engine_options)</code> | Builds the SQLAlchemy engine using the URL and expanded option dictionary. Real database access occurs when connections are used. |
| 27 | <code>if engine.dialect.name == "sqlite":</code> | Installs the next hook only when the actual engine dialect is SQLite. |
| 28 | <code>@event.listens_for(engine, "connect")</code> | Runs the following function whenever the engine opens a DBAPI connection. |
| 29 | <code>def enable_sqlite_foreign_keys(connection, _connection_record):</code> | Receives the raw SQLite connection and an unused connection-record argument. |
| 30 | <code>cursor = connection.cursor()</code> | Opens a low-level database cursor. |
| 31 | <code>cursor.execute("PRAGMA foreign_keys=ON")</code> | Enables SQLite foreign-key enforcement, which is otherwise off by default for a new connection. |
| 32 | <code>cursor.close()</code> | Closes that temporary cursor. |
| 35 | <code>SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)</code> | Builds the session factory. Queries do not automatically flush pending changes, and committed ORM objects retain their loaded attributes. |
| 38 | <code>def get_db() -&gt; Generator[Session, None, None]:</code> | Defines the dependency that yields one database session to a request. |
| 39 | <code>with SessionLocal() as session:</code> | Opens a session in a context manager so it is closed after the request finishes. |
| 40 | <code>yield session</code> | Hands the session to FastAPI's dependency system. This function does not automatically commit business changes. |
| 43 | <code>def initialize_database():</code> | Defines schema/table initialization used during startup and local seeding. |
| 44 | <code>if engine.dialect.name == "postgresql":</code> | Creates a separate schema only for PostgreSQL. |
| 45 | <code>with engine.begin() as connection:</code> | Opens a connection with a transaction; successful completion commits it. |
| 46 | <code>connection.execute(CreateSchema(settings.database_schema, if_not_exists=True))</code> | Creates the configured PostgreSQL schema only if it is absent. The database account needs permission to do this. |
| 47 | <code>Base.metadata.create_all(engine)</code> | Creates missing ORM tables after models have been imported. create_all is not a migration system and does not upgrade arbitrary existing table definitions. |

### `backend/models/user.py`

Defines the two database entities: an account and an individually revocable login session. Mapped[...] annotations let SQLAlchemy infer types and nullable behavior where not specified explicitly.

| Line | Code | Explanation |
| --- | --- | --- |
| 1 | <code>"""Only the account and authenticated-session entities needed for ResQ task."""</code> | Module docstring identifies the deliberately limited account/session scope. |
| 2 | <code>from datetime import datetime, timezone</code> | Imports date/time objects and the UTC timezone. |
| 3 | <code>from enum import Enum</code> | Imports Python's enumeration base. |
| 5 | <code>from sqlalchemy import Boolean, DateTime, Enum as SAEnum, ForeignKey, String</code> | Imports database column types, an SQL enum wrapper, and foreign-key support; aliases the SQL enum so it does not collide with Python Enum. |
| 6 | <code>from sqlalchemy.orm import Mapped, mapped_column</code> | Imports typed ORM field declarations and mapped-column creation. |
| 8 | <code>from ..database.connection import Base</code> | Imports the common ORM base and its schema metadata. |
| 11 | <code>def utc_now():</code> | Defines a reusable timestamp-producing function. |
| 12 | <code>return datetime.now(timezone.utc)</code> | Returns the current timezone-aware UTC datetime. |
| 15 | <code>class Role(str, Enum):</code> | Defines role values that behave as both string values and enum members. |
| 16 | <code>CITIZEN = "citizen"</code> | Defines the public citizen role. |
| 17 | <code>ADMIN = "admin"</code> | Defines the administrator role. |
| 18 | <code>RESPONSE_TEAM = "response_team"</code> | Defines the response-team role; the underscore form is used in stored data and JSON. |
| 21 | <code>class User(Base):</code> | Defines the user table model by inheriting the ORM base. |
| 22 | <code>__tablename__ = "users"</code> | Names the database table users; PostgreSQL puts it in the configured schema. |
| 23 | <code>id: Mapped[int] = mapped_column(primary_key=True)</code> | Defines an integer primary key, identifying each account. |
| 24 | <code>full_name: Mapped[str] = mapped_column(String(100))</code> | Stores a required name in a string column with a declared maximum length of 100. |
| 25 | <code>email: Mapped[str] = mapped_column(String(254), unique=True, index=True)</code> | Stores email in a unique index, supporting account lookup and preventing duplicate normalized addresses. With unique=True and index=True, SQLAlchemy defines one unique index rather than a separate unique constraint and index. |
| 26 | <code>password_hash: Mapped[str] = mapped_column(String(255))</code> | Stores a password hash rather than the plaintext password. |
| 27 | <code>role: Mapped[Role] = mapped_column(SAEnum(Role, values_callable=lambda values: [item.value for item in values], native_enum=False, create_constraint=True), default=Role.CITIZEN)</code> | Stores the lowercase Role values, defaults new ORM users to citizen, and uses a non-native enum with a database check constraint restricting allowed roles. |
| 28 | <code># Preserve the account response contract for integration with the shared app.</code> | Comment explains why the next compatibility field exists. |
| 29 | <code># Team membership/operations are managed by other members and are absent here.</code> | Comment states that actual team membership and operations are outside this module. |
| 30 | <code>team_id: Mapped[int &#124; None] = mapped_column(nullable=True)</code> | Stores an optional integer team_id. This minimal model does not define a teams table or a team foreign key. |
| 31 | <code>active: Mapped[bool] = mapped_column(Boolean, default=True)</code> | Marks new accounts active by default; authentication checks this field on each protected request. |
| 32 | <code>created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)</code> | Sets creation time with the callable utc_now when SQLAlchemy inserts the row. This is an application-side default, not a server-side SQL default. |
| 35 | <code>class TokenSession(Base):</code> | Defines the separately persisted login-session table model. |
| 36 | <code>__tablename__ = "token_sessions"</code> | Names the table token_sessions. |
| 37 | <code>id: Mapped[str] = mapped_column(String(36), primary_key=True)</code> | Uses a 36-character session identifier as its primary key; the token helper creates UUID-form strings. |
| 38 | <code>user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)</code> | Links each session to an existing user through a foreign key and indexes this account reference. |
| 39 | <code>created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)</code> | Records session creation using the same UTC callable default. |
| 40 | <code>expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))</code> | Stores the session's expiry timestamp, supplied by the JWT creation helper. |
| 41 | <code>revoked_at: Mapped[datetime &#124; None] = mapped_column(DateTime(timezone=True), nullable=True)</code> | Stores null while active and a UTC timestamp after logout. This enables immediate server-side revocation without deleting the row. |

### `backend/schemas/common.py`

Defines reusable JSON input and output policies. Schemas validate API data; they do not create database tables.

| Line | Code | Explanation |
| --- | --- | --- |
| 1 | <code>from datetime import datetime, timezone</code> | Imports datetimes and UTC for output normalization. |
| 3 | <code>from pydantic import BaseModel, ConfigDict, field_validator</code> | Imports Pydantic's model base, model configuration, and field validator. |
| 6 | <code>class InputModel(BaseModel):</code> | Defines the common parent for request models. |
| 7 | <code>model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)</code> | Rejects undeclared input fields and normally trims surrounding string whitespace. Auth requests override trimming to preserve passwords. |
| 10 | <code>class OutputModel(BaseModel):</code> | Defines the common parent for response models. |
| 11 | <code>model_config = ConfigDict(from_attributes=True)</code> | Allows response fields to be read from object attributes, so ORM User objects can be converted to JSON schemas. |
| 13 | <code>@field_validator("*", mode="after")</code> | Runs the next validator after parsing every field in derived output models. |
| 14 | <code>@classmethod</code> | Makes the validator a class method. |
| 15 | <code>def utc_dates(cls, value):</code> | Receives a parsed field value. |
| 16 | <code>if isinstance(value, datetime) and value.tzinfo is None:</code> | Detects datetime objects that lack timezone information. |
| 17 | <code>return value.replace(tzinfo=timezone.utc)</code> | Labels those naive datetimes as UTC; this attaches a timezone rather than converting a different timezone. |
| 18 | <code>return value</code> | Returns other values unchanged. The current auth response schemas have no datetime fields, so this helper has no visible timestamp effect there. |

### `backend/schemas/auth.py`

Specifies registration/login JSON and safe response fields. Extra fields are forbidden, so a client cannot add role or team_id to a registration request.

| Line | Code | Explanation |
| --- | --- | --- |
| 1 | <code>from pydantic import ConfigDict, EmailStr, Field, StrictStr, field_validator</code> | Imports Pydantic model options, email validation, field constraints, strict strings, and validators. |
| 3 | <code>from ..models import Role</code> | Imports the shared role enum for response validation. |
| 4 | <code>from .common import InputModel, OutputModel</code> | Imports the input/output schema parents. |
| 7 | <code>class RegisterRequest(InputModel):</code> | Defines the request body accepted by registration. |
| 8 | <code>model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)</code> | Rejects extra fields and turns off global string trimming so password whitespace stays significant. |
| 9 | <code>full_name: StrictStr = Field(min_length=3, max_length=100)</code> | Requires an actual string for full_name, with 3-100 characters after its explicit normalization. |
| 10 | <code>email: EmailStr = Field(max_length=254)</code> | Validates email structure and limits its length to 254 characters; it does not verify ownership by sending an email. |
| 11 | <code>password: StrictStr = Field(min_length=10, max_length=128)</code> | Requires a string password of 10-128 characters. There is no uppercase/digit/symbol composition rule here. |
| 13 | <code>@field_validator("full_name", mode="before")</code> | Runs name normalization before the field's type/length validation. |
| 14 | <code>@classmethod</code> | Declares the validator as a class method. |
| 15 | <code>def normalize_name(cls, value):</code> | Defines the name normalizer. |
| 16 | <code>return value.strip() if isinstance(value, str) else value</code> | Trims a string name but leaves non-string values for StrictStr to reject instead of coercing them. |
| 18 | <code>@field_validator("email", mode="before")</code> | Runs email normalization before email validation. |
| 19 | <code>@classmethod</code> | Declares the validator as a class method. |
| 20 | <code>def normalize_email(cls, value):</code> | Defines the registration email normalizer. |
| 21 | <code>return value.strip().lower() if isinstance(value, str) else value</code> | Trims and lowercases email strings; leaves other types to validation. The application's entire email address is normalized to lowercase. |
| 24 | <code>class LoginRequest(InputModel):</code> | Defines the login request body. |
| 25 | <code>model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)</code> | Forbids extra login fields and preserves password whitespace. |
| 26 | <code>email: EmailStr = Field(max_length=254)</code> | Requires a validated email with a maximum length of 254. |
| 27 | <code>password: StrictStr = Field(min_length=10, max_length=128)</code> | Applies the same strict-string and 10-128 character password policy during login. Too-short login input produces validation failure before password verification. |
| 29 | <code>@field_validator("email", mode="before")</code> | Registers a before-validation email normalizer for login. |
| 30 | <code>@classmethod</code> | Declares it as a class method. |
| 31 | <code>def normalize_email(cls, value):</code> | Defines the login email normalizer. |
| 32 | <code>return value.strip().lower() if isinstance(value, str) else value</code> | Trims and lowercases the supplied email, matching registration behavior. |
| 35 | <code>class UserResponse(OutputModel):</code> | Defines the safe public account representation returned by the API. |
| 36 | <code>id: int</code> | Includes the integer account ID. |
| 37 | <code>full_name: str</code> | Includes the user's full name. |
| 38 | <code>email: str</code> | Includes the normalized stored email. |
| 39 | <code>role: Role</code> | Includes the current role using the Role enum's string value in JSON. |
| 40 | <code>team_id: int &#124; None</code> | Includes optional team_id; it can be null. Password, hash, active flag, and creation timestamp are not exposed by this schema. |
| 43 | <code>class AuthResponse(OutputModel):</code> | Defines the successful registration/login response. |
| 44 | <code>access_token: str</code> | Includes the signed access token as a string. |
| 45 | <code>token_type: str = "bearer"</code> | Defaults token_type to bearer, describing how clients send the token in the Authorization header. |
| 46 | <code>user: UserResponse</code> | Includes the safe nested UserResponse rather than serializing all database columns. |

### `backend/utils/security.py`

Wraps password hashing and verification. The installed pwdlib PasswordHash.recommended implementation selects Argon2; generated hashes include the salt and verification parameters.

| Line | Code | Explanation |
| --- | --- | --- |
| 1 | <code>import secrets</code> | Imports cryptographically suitable random-generation helpers. |
| 3 | <code>from pwdlib import PasswordHash</code> | Imports the password-hashing wrapper provided by pwdlib. |
| 6 | <code>password_hasher = PasswordHash.recommended()</code> | Creates the recommended hasher once at module import. The installed implementation selects Argon2. |
| 7 | <code>dummy_password_hash = password_hasher.hash(secrets.token_urlsafe(24))</code> | Hashes a random dummy password once. Unknown-email login still performs a hash verification, reducing a simple difference in expensive work between existing and missing accounts. |
| 10 | <code>def hash_password(password: str) -&gt; str:</code> | Defines the helper used for registration and locally provisioned accounts. |
| 11 | <code>return password_hasher.hash(password)</code> | Hashes the plaintext password with the hasher's salt/parameters and returns its encoded hash. This is not reversible encryption. |
| 14 | <code>def verify_password(password: str, encoded: str) -&gt; bool:</code> | Defines verification against an already encoded stored hash. |
| 15 | <code>try:</code> | Begins handling invalid hash/value errors. |
| 16 | <code>return password_hasher.verify(password, encoded)</code> | Returns whether the submitted plaintext matches the encoded hash; a normal mismatch returns false. |
| 17 | <code>except (ValueError, TypeError):</code> | Catches the listed invalid-value/type failures instead of exposing them as ordinary authentication errors. |
| 18 | <code>return False</code> | Treats those caught failures as verification failure. This handler does not claim to catch every possible exception. |

### `backend/utils/jwt.py`

Creates a signed JWT tied to a database session and verifies incoming token signatures/claims. PyJWT is imported as jwt. A JWT is signed here, not encrypted; the secret never becomes a token claim.

| Line | Code | Explanation |
| --- | --- | --- |
| 1 | <code>from datetime import datetime, timedelta, timezone</code> | Imports UTC datetimes and a duration type for token expiry calculation. |
| 2 | <code>from uuid import uuid4</code> | Imports UUID generation for unique session IDs. |
| 4 | <code>import jwt</code> | Imports PyJWT's encode/decode helpers and error classes. |
| 5 | <code>from fastapi import HTTPException, status</code> | Imports HTTP errors and named HTTP status constants. |
| 6 | <code>from sqlalchemy.orm import Session</code> | Imports the ORM session type for annotations. |
| 8 | <code>from ..config import get_settings</code> | Imports access to validated signing/lifetime settings. |
| 9 | <code>from ..models import TokenSession, User</code> | Imports account/session models used to link tokens to persisted records. |
| 12 | <code>TOKEN_ISSUER = "resq-week1"</code> | Defines the issuer identifier included in and required from tokens. |
| 13 | <code>TOKEN_AUDIENCE = "resq-week1"</code> | Defines the audience identifier; this module expects tokens intended for this same app. |
| 16 | <code>def unauthorized() -&gt; HTTPException:</code> | Defines one reusable authentication-error constructor. |
| 17 | <code>return HTTPException(</code> | Begins constructing an HTTPException; callers raise the returned exception. |
| 18 | <code>status_code=status.HTTP_401_UNAUTHORIZED,</code> | Uses HTTP 401 for missing, invalid, expired, or revoked authentication. |
| 19 | <code>detail="Your session is invalid or expired. Please sign in again.",</code> | Provides the generic client-facing instruction to sign in again. |
| 20 | <code>headers={"WWW-Authenticate": "Bearer"},</code> | Adds the standard Bearer authentication challenge header. |
| 21 | <code>)</code> | Closes the multiline function call or constructor begun above. |
| 24 | <code>def create_session_token(db: Session, user: User) -&gt; str:</code> | Defines token creation for an existing ORM user and pending database transaction. |
| 25 | <code>settings = get_settings()</code> | Loads the cached configuration. |
| 26 | <code>issued_at = datetime.now(timezone.utc)</code> | Captures the issue time in UTC. |
| 27 | <code>expires_at = issued_at + timedelta(minutes=settings.jwt_expire_minutes)</code> | Computes expiry using the configured minutes, defaulting to 30. |
| 28 | <code>session_id = str(uuid4())</code> | Generates a new UUID string for this login session, allowing multiple separately revocable sessions per account. |
| 29 | <code>db.add(TokenSession(id=session_id, user_id=user.id, expires_at=expires_at))</code> | Adds the TokenSession row to the session. This helper does not commit; auth_result commits the transaction. |
| 30 | <code>return jwt.encode(</code> | Begins encoding and signing the claim dictionary. |
| 31 | <code>{"sub": str(user.id), "sid": session_id, "iat": issued_at, "exp": expires_at,</code> | Sets sub to the account ID string, sid to the persisted session ID, iat to issue time, and exp to expiry time. PyJWT serializes the datetime claims as JWT timestamps. |
| 32 | <code>"iss": TOKEN_ISSUER, "aud": TOKEN_AUDIENCE},</code> | Adds issuer and audience. No role is embedded; authorization later reads the current database role. |
| 33 | <code>settings.jwt_secret.get_secret_value(), algorithm="HS256",</code> | Extracts the secret only to sign using HMAC SHA-256. This same secret is needed to verify the signature. |
| 34 | <code>)</code> | Closes the multiline function call or constructor begun above. |
| 37 | <code>def decode_session_token(token: str) -&gt; dict:</code> | Defines verification/parsing for an incoming token string. |
| 38 | <code>try:</code> | Begins conversion of PyJWT token errors into the shared HTTP 401 response. |
| 39 | <code>payload = jwt.decode(</code> | Begins JWT decoding with verification enabled by default. |
| 40 | <code>token, get_settings().jwt_secret.get_secret_value(), algorithms=["HS256"],</code> | Checks with the configured secret and explicitly permits only HS256; the token cannot freely choose an algorithm. |
| 41 | <code>audience=TOKEN_AUDIENCE, issuer=TOKEN_ISSUER,</code> | Requires the expected audience and issuer values. |
| 42 | <code>options={"require": ["sub", "sid", "iat", "exp", "iss", "aud"]},</code> | Requires all six listed claims. PyJWT also validates applicable claim semantics such as expiration under its decode defaults; presence checks alone are not all the verification being performed. |
| 43 | <code>)</code> | Closes the multiline function call or constructor begun above. |
| 44 | <code>if not isinstance(payload["sub"], str) or not payload["sub"].isdigit():</code> | Requires a string subject made of digits before the permission layer converts it to an integer. |
| 45 | <code>raise unauthorized()</code> | Rejects an invalid subject using the shared 401 exception. |
| 46 | <code>if not isinstance(payload["sid"], str) or len(payload["sid"]) != 36:</code> | Requires sid to be a string of length 36. This length check alone is not full UUID syntax validation; the database lookup must also find the session. |
| 47 | <code>raise unauthorized()</code> | Rejects an invalid session-ID shape. |
| 48 | <code>return payload</code> | Returns the verified payload to the permission layer, which still must verify the persisted session and user. |
| 49 | <code>except jwt.InvalidTokenError:</code> | Catches PyJWT InvalidTokenError and its subclasses, including signature/expiry/claim validation failures. |
| 50 | <code>raise unauthorized() from None</code> | Raises the shared 401 without chained internal token-error details in the client response. |

### `backend/utils/permissions.py`

Connects bearer-token authentication to current database state and role authorization. Every protected request checks both the signed JWT and the persisted session/user.

| Line | Code | Explanation |
| --- | --- | --- |
| 1 | <code>from dataclasses import dataclass</code> | Imports a decorator for a small object with automatically generated initialization. |
| 2 | <code>from datetime import datetime, timezone</code> | Imports datetimes and UTC for persisted expiry checks. |
| 4 | <code>from fastapi import Depends, HTTPException</code> | Imports dependency injection and HTTP exceptions. |
| 5 | <code>from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer</code> | Imports bearer-header parsing and its resulting credential type. |
| 6 | <code>from sqlalchemy.orm import Session</code> | Imports the ORM session type. |
| 8 | <code>from ..database.connection import get_db</code> | Imports the database dependency. |
| 9 | <code>from ..models import Role, TokenSession, User</code> | Imports the role, saved session, and user models. |
| 10 | <code>from .jwt import decode_session_token, unauthorized</code> | Imports signed-token decoding and the shared 401 helper. |
| 13 | <code>bearer = HTTPBearer(auto_error=False)</code> | Creates a Bearer header parser. auto_error=False lets this module handle missing or unacceptable credentials with its own 401 response. |
| 16 | <code>@dataclass</code> | Makes Principal a dataclass, generating a constructor for its annotated fields. |
| 17 | <code>class Principal:</code> | Defines the authenticated request identity container. |
| 18 | <code>user: User</code> | Holds the current database User object. |
| 19 | <code>session: TokenSession</code> | Holds the exact persisted login session associated with the submitted token. |
| 22 | <code>def get_principal(</code> | Begins the central authentication dependency. |
| 23 | <code>credentials: HTTPAuthorizationCredentials &#124; None = Depends(bearer),</code> | Receives parsed HTTP Bearer credentials through dependency injection, or None if unavailable. |
| 24 | <code>db: Session = Depends(get_db),</code> | Receives a database session through dependency injection. |
| 25 | <code>) -&gt; Principal:</code> | Declares that successful authentication returns a Principal. |
| 26 | <code>if credentials is None:</code> | Checks for missing credentials before decoding anything. |
| 27 | <code>raise unauthorized()</code> | Rejects the request with HTTP 401. |
| 28 | <code>payload = decode_session_token(credentials.credentials)</code> | Verifies and decodes the credential's token string. |
| 29 | <code>token_session = db.get(TokenSession, payload["sid"])</code> | Finds the persisted TokenSession by the token's sid primary key. |
| 30 | <code>if token_session is None or token_session.revoked_at is not None:</code> | Rejects sessions that have been deleted/never existed or have a revocation timestamp. |
| 31 | <code>raise unauthorized()</code> | Raises the shared authentication error for that condition. |
| 32 | <code>expiry = token_session.expires_at</code> | Reads the persisted expiry, independently of the token's exp claim. |
| 33 | <code>if expiry.tzinfo is None:</code> | Detects a naive datetime, which can occur in SQLite-backed tests. |
| 34 | <code>expiry = expiry.replace(tzinfo=timezone.utc)</code> | Treats that naive stored value as UTC for comparison. |
| 35 | <code>if expiry &lt;= datetime.now(timezone.utc) or token_session.user_id != int(payload["sub"]):</code> | Rejects an expired database session or a session whose user_id differs from the token's subject. |
| 36 | <code>raise unauthorized()</code> | Raises HTTP 401 for those invalid session conditions. |
| 37 | <code>user = db.get(User, token_session.user_id)</code> | Loads the user from the database using the session's user reference. |
| 38 | <code>if user is None or not user.active:</code> | Rejects a missing or deactivated account, even when its token signature remains valid. |
| 39 | <code>raise unauthorized()</code> | Raises the shared authentication error. |
| 40 | <code>return Principal(user=user, session=token_session)</code> | Returns the validated current user and the exact session record for downstream handlers. |
| 43 | <code>def get_current_user(principal: Principal = Depends(get_principal)) -&gt; User:</code> | Defines a convenience dependency that unwraps the user from an authenticated Principal. |
| 44 | <code>return principal.user</code> | Returns the database user without duplicating authentication checks. |
| 47 | <code>def require_roles(*roles: Role):</code> | Defines a dependency factory accepting any number of allowed roles. |
| 48 | <code>def permission(user: User = Depends(get_current_user)) -&gt; User:</code> | Defines the returned dependency, first requiring the authenticated current user. |
| 49 | <code>if user.role not in roles:</code> | Checks the user's current database role against the roles captured by the surrounding factory call. |
| 50 | <code>raise HTTPException(status_code=403, detail="You do not have permission for this action.")</code> | Returns HTTP 403 when authentication succeeded but the role lacks permission. |
| 51 | <code>return user</code> | Provides the allowed user to the endpoint when the role check succeeds. |
| 52 | <code>return permission</code> | Returns the inner function so a router can pass it to Depends. The outer factory runs when the route is defined; the inner check runs per request. |

### `backend/services/auth_service.py`

Implements authentication business logic and transaction boundaries. Routers handle HTTP wiring; this service creates accounts, verifies passwords, issues sessions, and records logout.

| Line | Code | Explanation |
| --- | --- | --- |
| 1 | <code>from datetime import datetime, timezone</code> | Imports UTC time for revocation timestamps. |
| 3 | <code>from fastapi import HTTPException</code> | Imports HTTPException for service errors exposed through FastAPI. |
| 4 | <code>from sqlalchemy import select</code> | Imports SQLAlchemy's SELECT statement builder. |
| 5 | <code>from sqlalchemy.exc import IntegrityError</code> | Imports the database integrity-error class used for duplicate-registration handling. |
| 6 | <code>from sqlalchemy.orm import Session</code> | Imports the ORM session type. |
| 8 | <code>from ..models import Role, TokenSession, User</code> | Imports role and database models. |
| 9 | <code>from ..schemas.auth import AuthResponse, LoginRequest, RegisterRequest, UserResponse</code> | Imports validated input objects and safe output objects. |
| 10 | <code>from ..utils.jwt import create_session_token</code> | Imports the helper that stages a login session and signs its JWT. |
| 11 | <code>from ..utils.security import dummy_password_hash, hash_password, verify_password</code> | Imports dummy verification data and real password helpers. |
| 14 | <code>def auth_result(db: Session, user: User) -&gt; AuthResponse:</code> | Defines the shared successful-authentication response builder. |
| 15 | <code>token = create_session_token(db, user)</code> | Stages a new TokenSession row and generates its signed token. |
| 16 | <code>db.commit()</code> | Commits the transaction so the account/session is persisted before returning success. |
| 17 | <code>return AuthResponse(access_token=token, user=UserResponse.model_validate(user))</code> | Returns the token plus the permitted public user fields, validating the ORM object through from_attributes. |
| 20 | <code>def register(db: Session, data: RegisterRequest) -&gt; AuthResponse:</code> | Defines citizen registration using the validated request schema. |
| 21 | <code>email = str(data.email).lower()</code> | Converts the validated email to a lowercase string for database matching/storage. |
| 22 | <code>if db.scalar(select(User).where(User.email == email)):</code> | Looks up an existing user using the normalized email and checks whether one was returned. |
| 23 | <code>raise HTTPException(status_code=409, detail="An account already exists for this email.")</code> | Returns HTTP 409 when the email already has an account. |
| 24 | <code>user = User(full_name=data.full_name, email=email,</code> | Begins constructing a new ORM User with the normalized identity fields. |
| 25 | <code>password_hash=hash_password(data.password), role=Role.CITIZEN)</code> | Hashes the exact submitted password and forces the role to CITIZEN regardless of client intent. |
| 26 | <code>db.add(user)</code> | Stages the new account in the ORM session. |
| 27 | <code>try:</code> | Begins handling database integrity errors around insertion/session issuance. |
| 28 | <code>db.flush()</code> | Flushes the INSERT without committing, obtaining user.id so the login session can reference it. |
| 29 | <code>return auth_result(db, user)</code> | Creates the login session, commits the account and session, and returns the AuthResponse. Registration therefore signs the user in immediately. |
| 30 | <code>except IntegrityError:</code> | Catches an integrity violation, including a uniqueness conflict if concurrent requests pass the earlier email lookup. |
| 31 | <code>db.rollback()</code> | Rolls the failed transaction back so the session is usable/clean afterward. |
| 32 | <code>raise HTTPException(status_code=409, detail="An account already exists for this email.") from None</code> | Maps the caught integrity error to the duplicate-email HTTP 409 response and suppresses exception chaining. All caught IntegrityError instances receive this message, not only email-specific ones. |
| 35 | <code>def login(db: Session, data: LoginRequest) -&gt; AuthResponse:</code> | Defines login using validated credentials. |
| 36 | <code>user = db.scalar(select(User).where(User.email == str(data.email).lower()))</code> | Looks up the normalized email and returns its User object or None. |
| 37 | <code>encoded = user.password_hash if user else dummy_password_hash</code> | Chooses the real stored hash if the user exists, otherwise the precomputed dummy hash. |
| 38 | <code>password_valid = verify_password(data.password, encoded)</code> | Runs password verification in both cases rather than immediately returning on missing email. |
| 39 | <code>if not user or not password_valid or not user.active:</code> | Rejects an unknown user, wrong password, or inactive account. Short-circuit evaluation avoids accessing active on None. |
| 40 | <code>raise HTTPException(status_code=401, detail="Email or password is incorrect.",</code> | Returns the same generic HTTP 401 message for those cases, avoiding direct disclosure of which credential failed. |
| 41 | <code>headers={"WWW-Authenticate": "Bearer"})</code> | Adds the Bearer authentication challenge header. |
| 42 | <code>return auth_result(db, user)</code> | Creates and commits a fresh session/token for this successful login. |
| 45 | <code>def logout(db: Session, token_session: TokenSession) -&gt; None:</code> | Defines logout for the already authenticated current TokenSession. |
| 46 | <code>token_session.revoked_at = datetime.now(timezone.utc)</code> | Marks only this session revoked at the current UTC time. |
| 47 | <code>db.commit()</code> | Commits the revocation, making later requests with that token fail the database session check. Other sessions for the user remain active. |

### `backend/routers/auth.py`

Exposes the registration, login, and logout API. FastAPI validates JSON against the declared request type before calling these handlers.

| Line | Code | Explanation |
| --- | --- | --- |
| 1 | <code>from fastapi import APIRouter, Depends, Response, status</code> | Imports router creation, dependency injection, explicit empty responses, and HTTP status constants. |
| 2 | <code>from sqlalchemy.orm import Session</code> | Imports the ORM Session type used in route signatures. |
| 4 | <code>from ..database.connection import get_db</code> | Imports the database-session dependency. |
| 5 | <code>from ..schemas.auth import AuthResponse, LoginRequest, RegisterRequest</code> | Imports input and output authentication schemas. |
| 6 | <code>from ..services import auth_service</code> | Imports the business-logic module. |
| 7 | <code>from ..utils.permissions import Principal, get_principal</code> | Imports the authenticated identity container/dependency required by logout. |
| 10 | <code>router = APIRouter(prefix="/api/auth", tags=["Authentication"])</code> | Creates a router whose paths all begin /api/auth and groups it under Authentication in API docs. |
| 13 | <code>@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)</code> | Registers POST /api/auth/register, filters success through AuthResponse, and returns HTTP 201 on successful creation. |
| 14 | <code>def register(data: RegisterRequest, db: Session = Depends(get_db)):</code> | Receives a validated RegisterRequest plus an injected database session. |
| 15 | <code>"""Create a citizen account. Privileged roles cannot be self-registered."""</code> | Documents that public registration cannot create privileged roles; the service and extra-field validation enforce it. |
| 16 | <code>return auth_service.register(db, data)</code> | Delegates registration to the service and returns its response. |
| 19 | <code>@router.post("/login", response_model=AuthResponse)</code> | Registers POST /api/auth/login with AuthResponse; successful responses default to HTTP 200. |
| 20 | <code>def login(data: LoginRequest, db: Session = Depends(get_db)):</code> | Receives validated login JSON and the database session. |
| 21 | <code>return auth_service.login(db, data)</code> | Delegates password checking/session issuance to the service. |
| 24 | <code>@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)</code> | Registers POST /api/auth/logout and declares HTTP 204 success, meaning no response body. |
| 25 | <code>def logout(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):</code> | Requires a valid Principal and the database session. FastAPI normally caches repeated get_db dependency calls within a request, so nested authentication and this handler share that request's session. |
| 26 | <code>"""Revoke the current bearer session immediately."""</code> | Documents immediate revocation of the current bearer session. |
| 27 | <code>auth_service.logout(db, principal.session)</code> | Tells the service to revoke the exact session authenticated by get_principal. |
| 28 | <code>return Response(status_code=status.HTTP_204_NO_CONTENT)</code> | Returns an explicitly empty HTTP 204 response rather than a JSON message. |

### `backend/routers/users.py`

Exposes the authenticated account-details endpoint. Its response schema prevents the password hash from becoming part of the JSON result.

| Line | Code | Explanation |
| --- | --- | --- |
| 1 | <code>from fastapi import APIRouter, Depends</code> | Imports the router and dependency mechanism. |
| 3 | <code>from ..models import User</code> | Imports the ORM user type for annotation. |
| 4 | <code>from ..schemas.auth import UserResponse</code> | Imports the safe public account-response schema. |
| 5 | <code>from ..utils.permissions import get_current_user</code> | Imports the authenticated current-user dependency. |
| 8 | <code>router = APIRouter(prefix="/api/users", tags=["Users"])</code> | Creates the /api/users router and its documentation tag. |
| 11 | <code>@router.get("/me", response_model=UserResponse)</code> | Registers GET /api/users/me with response_model=UserResponse. |
| 12 | <code>def me(user: User = Depends(get_current_user)):</code> | Requires an authenticated database user; missing/invalid sessions fail before this handler runs. |
| 13 | <code>return user</code> | Returns the ORM user. FastAPI extracts only the declared UserResponse fields, excluding password_hash and other undeclared columns. |

### `backend/routers/workspaces.py`

Provides three real protected endpoints to demonstrate role permissions. They return explanatory JSON; they are not operational disaster-management modules.

| Line | Code | Explanation |
| --- | --- | --- |
| 1 | <code>"""Small real endpoints to demonstrate role permissions without other members' modules."""</code> | Module docstring states the role-demonstration scope. |
| 2 | <code>from fastapi import APIRouter, Depends</code> | Imports route declaration and dependency injection. |
| 4 | <code>from ..models import Role, User</code> | Imports the role enum and ORM user type. |
| 5 | <code>from ..utils.permissions import require_roles</code> | Imports the role-permission dependency factory. |
| 7 | <code>router = APIRouter(prefix="/api/workspaces", tags=["Role access demonstration"])</code> | Creates /api/workspaces routes under the role-access documentation group. |
| 10 | <code>def workspace(role: Role, title: str):</code> | Defines a helper for the common successful-workspace response. |
| 11 | <code>return {"role": role.value, "title": title, "message": "Your role is authorized to open this workspace. This module demonstrates authentication and permissions only."}</code> | Returns role, display title, and a message explaining that access was authorized. It does not fetch incidents, tasks, or other operational records. |
| 14 | <code>@router.get("/citizen")</code> | Registers GET /api/workspaces/citizen. |
| 15 | <code>def citizen_workspace(_user: User = Depends(require_roles(Role.CITIZEN))):</code> | Runs authentication and allows only the citizen role. _user is available after the check but unused by this demonstration handler. |
| 16 | <code>return workspace(Role.CITIZEN, "Citizen workspace")</code> | Returns the citizen response after permission succeeds. |
| 19 | <code>@router.get("/admin")</code> | Registers GET /api/workspaces/admin. |
| 20 | <code>def admin_workspace(_user: User = Depends(require_roles(Role.ADMIN))):</code> | Allows only ADMIN; an admin does not automatically gain the citizen or response-team route in this code. |
| 21 | <code>return workspace(Role.ADMIN, "Admin workspace")</code> | Returns the admin response. |
| 24 | <code>@router.get("/response-team")</code> | Registers GET /api/workspaces/response-team; the URL uses a hyphen even though the stored role value uses an underscore. |
| 25 | <code>def response_team_workspace(_user: User = Depends(require_roles(Role.RESPONSE_TEAM))):</code> | Allows only the response-team role after authentication. |
| 26 | <code>return workspace(Role.RESPONSE_TEAM, "Response team workspace")</code> | Returns the response-team response. |

### `backend/main.py`

Creates the FastAPI application, handles startup/shutdown, applies response/CORS policies, exposes health, and mounts all routers. Imported model definitions register database metadata before startup creates tables.

| Line | Code | Explanation |
| --- | --- | --- |
| 1 | <code>from contextlib import asynccontextmanager</code> | Imports a decorator that turns an async generator into an async context manager for application lifespan. |
| 3 | <code>from fastapi import Depends, FastAPI, Request</code> | Imports dependency injection, app creation, and the HTTP request type. |
| 4 | <code>from fastapi.middleware.cors import CORSMiddleware</code> | Imports cross-origin request middleware. |
| 5 | <code>from fastapi.responses import JSONResponse</code> | Imports an explicit JSON response class for errors/health failures. |
| 6 | <code>from sqlalchemy import text</code> | Imports SQLAlchemy's wrapper for textual SQL. |
| 7 | <code>from sqlalchemy.exc import SQLAlchemyError</code> | Imports the common SQLAlchemy database-error base class. |
| 8 | <code>from sqlalchemy.orm import Session</code> | Imports the ORM session type for health's dependency annotation. |
| 10 | <code>from .config import get_settings</code> | Imports settings loading. |
| 11 | <code>from .database.connection import Base, engine, get_db, initialize_database</code> | Imports the base, engine, database dependency, and initializer. Base is imported but not otherwise referenced directly in this file. |
| 12 | <code>from . import models  # Register all table metadata before creating the schema.</code> | Imports models for the side effect of registering User and TokenSession tables in Base.metadata before table initialization. |
| 13 | <code>from .routers import auth, users, workspaces</code> | Imports the three router modules. |
| 16 | <code>settings = get_settings()</code> | Loads validated app settings once through the cache. |
| 19 | <code>@asynccontextmanager</code> | Marks the following async generator as the app's lifespan context manager. |
| 20 | <code>async def lifespan(_app: FastAPI):</code> | Defines startup/shutdown behavior; _app is provided by FastAPI but unused. |
| 21 | <code>initialize_database()</code> | Creates the schema and missing tables before the application starts serving requests. It does not provision demo accounts; setup runs seed separately. |
| 22 | <code>yield</code> | Hands control to FastAPI while it serves requests; the following line runs during normal shutdown. |
| 23 | <code>engine.dispose()</code> | Disposes the engine's connection pool during shutdown; this does not stop the PostgreSQL server. |
| 26 | <code>app = FastAPI(</code> | Begins constructing the FastAPI application. |
| 27 | <code>title="ResQ Kerala — Week 1", version=settings.app_version,</code> | Sets the API documentation title and configured version. |
| 28 | <code>description="Registration, login, logout and server-enforced role permissions.",</code> | Sets the API documentation description of this module's scope. |
| 29 | <code>lifespan=lifespan,</code> | Attaches the startup/shutdown context manager. |
| 30 | <code>)</code> | Closes the multiline function call or constructor begun above. |
| 31 | <code>app.add_middleware(</code> | Begins adding middleware to the application. |
| 32 | <code>CORSMiddleware, allow_origins=settings.allowed_origins,</code> | Applies CORS using the configured allowed browser origins. |
| 33 | <code>allow_credentials=False, allow_methods=["GET", "POST"],</code> | Disables credentialed CORS such as cookies and allows browser cross-origin GET/POST requests. Authentication uses an explicitly supplied Authorization header, not a cookie session. |
| 34 | <code>allow_headers=["Authorization", "Content-Type"],</code> | Allows Authorization and Content-Type in cross-origin request headers. CORS controls browser access; it does not replace server authentication or restrict direct non-browser clients. |
| 35 | <code>)</code> | Closes the multiline function call or constructor begun above. |
| 38 | <code>@app.middleware("http")</code> | Registers custom middleware for HTTP requests. |
| 39 | <code>async def response_headers(request: Request, call_next):</code> | Receives the request and the next-handler callable. |
| 40 | <code>response = await call_next(request)</code> | Awaits the remaining application pipeline to get its response. |
| 41 | <code>response.headers["X-Content-Type-Options"] = "nosniff"</code> | Adds nosniff, instructing browsers not to guess a different content type. |
| 42 | <code>if request.url.path.startswith("/api/"):</code> | Checks whether the request path belongs to /api/. |
| 43 | <code>response.headers["Cache-Control"] = "no-store"</code> | Marks API responses no-store so caches should not retain authentication/account responses. The condition does not include /health or /docs. |
| 44 | <code>return response</code> | Returns the response with the additional headers. |
| 47 | <code>@app.exception_handler(SQLAlchemyError)</code> | Registers a handler for otherwise unhandled SQLAlchemyError exceptions. |
| 48 | <code>async def database_error(_request: Request, _error: SQLAlchemyError):</code> | Defines that handler; the actual request and exception are intentionally unused in its output. |
| 49 | <code># Connection strings and driver diagnostics can contain credentials.</code> | Explains why connection details/driver diagnostics are not returned to the client. |
| 50 | <code>return JSONResponse(status_code=503, content={"detail": "The database is temporarily unavailable. Please try again."})</code> | Returns generic HTTP 503 JSON instead of leaking database internals. More specific service-handled integrity errors still use their HTTP 409 response. |
| 53 | <code>@app.get("/health", tags=["System"])</code> | Registers GET /health in the System API-docs group. |
| 54 | <code>def health(db: Session = Depends(get_db)):</code> | Injects a database session into the health handler. |
| 55 | <code>try:</code> | Begins the database connectivity probe. |
| 56 | <code>db.execute(text("SELECT 1"))</code> | Executes SELECT 1 through the database session. This checks a basic round trip, not the entire authentication workflow or all table contents. |
| 57 | <code>except SQLAlchemyError:</code> | Handles database errors encountered by that probe. |
| 58 | <code>return JSONResponse(status_code=503, content={</code> | Begins a specific HTTP 503 health response. |
| 59 | <code>"status": "unhealthy", "version": settings.app_version, "database": "unavailable",</code> | Reports unhealthy status, app version, and an unavailable database without connection details. |
| 60 | <code>})</code> | Closes the multiline function call or constructor begun above. |
| 61 | <code>return {"status": "ok", "version": settings.app_version, "database": "connected"}</code> | On a successful probe, reports ok, version, and connected database. |
| 64 | <code>app.include_router(auth.router)</code> | Mounts /api/auth registration/login/logout routes. |
| 65 | <code>app.include_router(users.router)</code> | Mounts /api/users/me. |
| 66 | <code>app.include_router(workspaces.router)</code> | Mounts the three protected role-workspace routes. |

### `backend/seed.py`

Locally provisions three demonstration roles without allowing privileged public registration. This module is executed by setup, not exposed as an HTTP endpoint. The guide describes credential handling without reading the private generated credential file.

| Line | Code | Explanation |
| --- | --- | --- |
| 1 | <code>"""Provision local demonstration accounts for the three roles, without public role selection."""</code> | Docstring states the local provisioning purpose and separation from public registration. |
| 2 | <code>import json</code> | Imports JSON reading/writing. |
| 3 | <code>import secrets</code> | Imports cryptographic random generation. |
| 5 | <code>from sqlalchemy import select</code> | Imports SQLAlchemy SELECT for existing-account lookup. |
| 7 | <code>from .config import WORKSPACE_ROOT</code> | Imports the project root for a predictable local output location. |
| 8 | <code>from .database.connection import SessionLocal, initialize_database</code> | Imports the database session factory and schema/table initialization. |
| 9 | <code>from .models import Role, User</code> | Imports roles and accounts; importing models also registers their metadata. |
| 10 | <code>from .utils.security import hash_password</code> | Imports real password hashing for seeded accounts. |
| 13 | <code>def seed():</code> | Defines the local seeding routine. |
| 14 | <code>initialize_database()</code> | Ensures the demo schema/tables exist before inserting users. |
| 15 | <code>destination = WORKSPACE_ROOT / ".runtime" / "demo-accounts.json"</code> | Sets the private demo credential record location under .runtime; its contents are not embedded in this guide. |
| 16 | <code>previous = json.loads(destination.read_text()) if destination.exists() else None</code> | Reads an existing generated JSON record when present, otherwise uses None. Invalid JSON would raise an error; this line does not repair it. |
| 17 | <code>password = previous["password"] if previous else secrets.token_urlsafe(20)</code> | Reuses the previously recorded demonstration password, or generates a random URL-safe password for new local setup. |
| 18 | <code>accounts = [</code> | Begins the fixed three-account specification list. |
| 19 | <code>{"email": "citizen@resq.example.com", "full_name": "Demo Citizen", "role": Role.CITIZEN},</code> | Defines the example citizen account; this address is a source-code demo identifier, not a secret. |
| 20 | <code>{"email": "admin@resq.example.com", "full_name": "Demo Admin", "role": Role.ADMIN},</code> | Defines the example administrator account, which public registration cannot provision. |
| 21 | <code>{"email": "team@resq.example.com", "full_name": "Demo Response Team", "role": Role.RESPONSE_TEAM},</code> | Defines the example response-team account. |
| 22 | <code>]</code> | Closes the list begun above. |
| 23 | <code>created = []</code> | Creates a list tracking which email addresses are newly inserted on this run. |
| 24 | <code>with SessionLocal() as db:</code> | Opens a database session that closes at the end of the block. |
| 25 | <code>for data in accounts:</code> | Iterates the three local account specifications. |
| 26 | <code>user = db.scalar(select(User).where(User.email == data["email"]))</code> | Looks up each exact demo email to avoid inserting it twice. |
| 27 | <code>if user is None:</code> | Inserts only when that address does not already exist. Existing users' password, role, and name are not updated. |
| 28 | <code>db.add(User(**data, password_hash=hash_password(password)))</code> | Expands the account dictionary into User fields and hashes the shared demonstration password before storing it. |
| 29 | <code>created.append(data["email"])</code> | Records the new account's email for later metadata/output. |
| 30 | <code>db.commit()</code> | Commits all newly staged accounts in one transaction. |
| 31 | <code>if created or not previous:</code> | Writes local metadata if any account was created or no previous credential record existed. |
| 32 | <code>destination.parent.mkdir(parents=True, exist_ok=True)</code> | Creates the destination directory and any missing parents, accepting an already existing directory. |
| 33 | <code>destination.write_text(json.dumps({"password": password, "accounts": [{**data, "role": data["role"].value, "uses_shared_password": data["email"] in created or bool(previous)} for data in accounts]}, indent=2), encoding="utf-8")</code> | Writes UTF-8 JSON containing the local shared demo password and account metadata. Role enums become string values. uses_shared_password is true for a newly created account or when any prior credential record exists; this expression does not actually reverify existing accounts' hashes. |
| 34 | <code>print(f"Authentication demo ready; created {len(created)} account(s). Local details: .runtime/demo-accounts.json")</code> | Prints only the number created and the local file location, avoiding the actual password in terminal output. |
| 37 | <code>if __name__ == "__main__":</code> | Checks whether Python is executing this module as the main program, as in python -m backend.seed. |
| 38 | <code>seed()</code> | Runs seed only in that execution mode; importing backend.seed alone does not provision accounts. |

## Frontend code

Every nonblank physical source line in the eight frontend files is explained below using its actual file line number. Blank lines only separate logical sections for readability and have no executable effect. The Code column uses escaped inline HTML code so JSX angle brackets, backticks, and pipe characters remain readable inside Markdown tables.

Read the request flow as: index.html → main.jsx → App → Login or authenticated views → api.js → Vite proxy → backend. State setters schedule React rerenders; event handlers run in response to user actions; effects coordinate requests and listeners with cleanup. Displayed labels and hidden navigation do not enforce access: the protected backend endpoints make those decisions.

Behavior limits visible in this source: this is an authentication/role-permissions demonstration, not a disaster incident workflow. There is no token-refresh request, client router, cross-tab session synchronization, or independent account-update form. The access table normalizes successful requests to 200. The complete session is stored in JavaScript-accessible sessionStorage; backend profile verification is therefore essential to the sign-in flow. This explanation describes source behavior without claiming a new browser or network test.

### `frontend/src/main.jsx`

**Purpose:** React browser entry point.

The HTML module script loads this file. It loads the application and its global stylesheet, then mounts the component tree inside the HTML element whose id is root. StrictMode adds development checks; in development, effects can be set up, cleaned up, and set up again to reveal lifecycle problems.

**Coverage:** 8 physical lines; 7 nonblank lines explained; 1 blank line is a readability separator.

| Line | Code | Explanation |
| --- | --- | --- |
| 1 | <code>import React from 'react';</code> | Imports React so the file can refer to React.StrictMode. |
| 2 | <code>import ReactDOM from 'react-dom/client';</code> | Imports the modern browser renderer from react-dom/client, exposing createRoot. |
| 3 | <code>import App from './App';</code> | Imports the default App component from the neighboring App.jsx module; Vite resolves the omitted extension. |
| 4 | <code>import './styles.css';</code> | Imports the shared CSS as a side effect so Vite includes the styles in the page or production bundle. |
| 6 | <code>ReactDOM.createRoot(document.getElementById('root')).render(</code> | Finds the root HTML container, creates a React root, and starts rendering its component tree. The container must exist in index.html. |
| 7 | <code>&lt;React.StrictMode&gt;&lt;App /&gt;&lt;/React.StrictMode&gt;,</code> | Renders App inside StrictMode. Its extra checks apply during development; it does not provide authentication or authorization. |
| 8 | <code>);</code> | Closes the render call. The trailing comma after its JSX argument is permitted JavaScript syntax. |

### `frontend/src/App.jsx`

**Purpose:** Session lifecycle, authenticated layout, account view, and role permission checks.

App restores a tab session and verifies it through GET /api/users/me before rendering the signed-in layout. Login also verifies that endpoint before accepting the user. PermissionsWorkspace concurrently calls all three protected workspace endpoints so the table shows server acceptance or refusal. Account displays the verified profile. Navigation switches local React state between workspace and account; it does not change the URL or use a router.

**Coverage:** 179 physical lines; 166 nonblank lines explained; 13 blank lines are readability separators.

| Line | Code | Explanation |
| --- | --- | --- |
| 1 | <code>import { useEffect, useState } from 'react';</code> | Imports useState for component memory and useEffect for requests/listeners that run after rendering. |
| 2 | <code>import { ArrowRight, CheckCircle2, LayoutDashboard, LoaderCircle, LockKeyhole, LogOut, RefreshCw, ShieldCheck, UserRound, Waves } from 'lucide-react';</code> | Imports ten Lucide React SVG icon components used for branding, loading, navigation, success, permissions, and sign-out. |
| 3 | <code>import Login from './components/shared/Login';</code> | Imports the sign-in/registration form component that is shown when App has no authenticated user. |
| 4 | <code>import { api, clearSession, readSession, saveSession, SESSION_EXPIRED_EVENT } from './services/api';</code> | Imports the API request helper, session storage helpers, and the custom event name used to announce session expiration. |
| 6 | <code>const workspaces = [</code> | Begins the fixed list of the three role workspaces that will be checked and labeled in the interface. |
| 7 | <code>{ role: 'citizen', label: 'Citizen', path: '/api/workspaces/citizen' },</code> | Describes the citizen role, its display label, and its protected backend URL. |
| 8 | <code>{ role: 'admin', label: 'Admin', path: '/api/workspaces/admin' },</code> | Describes the admin role, its display label, and its protected backend URL. |
| 9 | <code>{ role: 'response_team', label: 'Response team', path: '/api/workspaces/response-team' },</code> | Describes the response_team role and its URL. The stored role uses an underscore while the URL uses a hyphen. |
| 10 | <code>];</code> | Closes the workspace array. |
| 11 | <code>const roleLabel = role =&gt; workspaces.find(item =&gt; item.role === role)?.label &#124;&#124; role;</code> | Defines a helper that finds a role's friendly label. Optional chaining tolerates an unknown role, and logical OR falls back to the raw role string. |
| 13 | <code>function PermissionsWorkspace({ user }) {</code> | Defines PermissionsWorkspace and extracts user from its props. This component checks and displays the backend permissions for that user. |
| 14 | <code>const [results, setResults] = useState([]);</code> | Stores an initially empty results array. Each completed check will contribute a workspace object plus status and payload or error. |
| 15 | <code>const [busy, setBusy] = useState(true);</code> | Starts busy as true so the first render shows loading while requests are prepared. |
| 16 | <code>const [attempt, setAttempt] = useState(0);</code> | Stores an integer retry counter. Increasing it changes an effect dependency and reruns the permission checks. |
| 18 | <code>useEffect(() =&gt; {</code> | Starts the effect that performs requests after rendering and reruns whenever one of its dependencies changes. |
| 19 | <code>const controller = new AbortController();</code> | Creates an AbortController for this effect run so cleanup can cancel its fetch requests. |
| 20 | <code>setBusy(true);</code> | Marks the checks as busy, disabling the retry button and selecting loading text/icons. |
| 21 | <code>setResults([]);</code> | Clears previous results so stale access results are not shown while the new checks run. |
| 22 | <code>Promise.all(workspaces.map(async workspace =&gt; {</code> | Maps every workspace to an asynchronous request and wraps the resulting promises in Promise.all. Requests begin concurrently; the output array preserves workspace order. |
| 23 | <code>try {</code> | Begins handling the result or error of this individual workspace request. |
| 24 | <code>const payload = await api(workspace.path, { signal: controller.signal });</code> | Calls the shared API helper with that protected path and the effect's cancellation signal. The helper adds the saved bearer token. |
| 25 | <code>return { ...workspace, status: 200, payload };</code> | Returns the workspace fields and parsed server payload for a successful request. The displayed status is explicitly set to 200, even if fetch accepted another successful 2xx status. |
| 26 | <code>} catch (error) {</code> | Handles errors raised by the request helper for this workspace. |
| 27 | <code>if (error.name === 'AbortError') throw error;</code> | Rethrows cancellation errors so cancellation is not recorded as an ordinary failed permission check. |
| 28 | <code>return { ...workspace, status: error.status, error: error.message };</code> | Converts an ordinary failure into a result entry. HTTP failures have a status; network failures may have no status. The displayed message comes from error.message. |
| 29 | <code>}</code> | Closes the individual try/catch block. |
| 30 | <code>}))</code> | Closes the asynchronous map and Promise.all call. |
| 31 | <code>.then(value =&gt; { if (!controller.signal.aborted) setResults(value); })</code> | After all requests finish, updates results only if this effect has not been canceled. |
| 32 | <code>.catch(() =&gt; {})</code> | Consumes rejection from the whole group, including cancellation. This handler intentionally displays no extra error; non-cancellation request failures already become table entries. |
| 33 | <code>.finally(() =&gt; { if (!controller.signal.aborted) setBusy(false); });</code> | Clears busy after completion only when this effect is still active, avoiding a canceled run changing the active UI. |
| 34 | <code>return () =&gt; controller.abort();</code> | Returns effect cleanup, which aborts its requests when the component unmounts or dependencies change. |
| 35 | <code>}, [user.id, user.role, attempt]);</code> | Declares the dependencies: a different user id, a different role, or a larger retry counter starts a fresh permission check. |
| 37 | <code>const current = results.find(item =&gt; item.role === user.role);</code> | Finds the check matching the signed-in user's role; the hero uses this entry rather than another role's response. |
| 38 | <code>return (</code> | Starts returning the JSX that React will turn into the permission page. |
| 39 | <code>&lt;&gt;</code> | Opens a React fragment, grouping sibling elements without adding an extra HTML wrapper. |
| 40 | <code>&lt;div className="page-heading"&gt;</code> | Opens the page heading container styled by page-heading. |
| 41 | <code>&lt;div&gt;&lt;span className="eyebrow"&gt;RESQ · WEEK 1&lt;/span&gt;&lt;h1&gt;{roleLabel(user.role)} workspace&lt;/h1&gt;&lt;p&gt;Authentication and role access, verified through the backend.&lt;/p&gt;&lt;/div&gt;</code> | Shows the project label, friendly role-specific heading, and description of backend verification. JavaScript expressions inside braces insert computed values. |
| 42 | <code>&lt;button className="button secondary" onClick={() =&gt; setAttempt(value =&gt; value + 1)} disabled={busy}&gt;&lt;RefreshCw size={16} className={busy ? 'spin' : ''} /&gt;Check access again&lt;/button&gt;</code> | Shows the retry button. Clicking increments attempt with a functional state update; disabled prevents repeat clicks while busy. RefreshCw spins during the check. |
| 43 | <code>&lt;/div&gt;</code> | Closes the heading container. |
| 44 | <code>&lt;section className="workspace-hero" aria-label="Your role access"&gt;</code> | Opens the hero section and gives assistive technology the descriptive label Your role access. |
| 45 | <code>&lt;span className="hero-icon"&gt;&lt;ShieldCheck size={32} /&gt;&lt;/span&gt;</code> | Displays a shield icon inside the styled hero icon container. |
| 46 | <code>&lt;div&gt;</code> | Opens the hero's text container. |
| 47 | <code>&lt;span className="eyebrow"&gt;YOUR SIGNED-IN ROLE&lt;/span&gt;</code> | Shows the fixed small label introducing the currently signed-in role. |
| 48 | <code>&lt;h2&gt;{busy ? 'Checking workspace permissions…' : current?.payload?.title &#124;&#124; 'Workspace access needs attention'}&lt;/h2&gt;</code> | Shows loading text while busy; otherwise uses the current endpoint's payload.title, falling back to an attention message when no usable title exists. |
| 49 | <code>&lt;p&gt;{busy ? 'The server is checking access to each role workspace using your session.' : current?.payload?.message &#124;&#124; current?.error &#124;&#124; 'Your current role could not be verified.'}&lt;/p&gt;</code> | Shows loading guidance or, when settled, the endpoint's payload.message, then its error message, then a generic verification failure. Optional chaining prevents access through missing objects. |
| 50 | <code>{!busy &amp;&amp; current?.status === 200 &amp;&amp; &lt;span className="access-badge"&gt;&lt;CheckCircle2 size={15} /&gt;Server accepted your {roleLabel(user.role).toLowerCase()} session&lt;/span&gt;}</code> | Renders the acceptance badge only after loading ends and the current result has status 200. It lowercases the friendly role label for the sentence. |
| 51 | <code>&lt;/div&gt;</code> | Closes the hero text container. |
| 52 | <code>&lt;/section&gt;</code> | Closes the hero section. |
| 53 | <code>&lt;section className="panel" aria-labelledby="permissions-heading"&gt;</code> | Opens the permissions panel and connects its accessible name to the heading with id permissions-heading. |
| 54 | <code>&lt;div className="panel-heading"&gt;&lt;div&gt;&lt;h2 id="permissions-heading"&gt;Workspace permissions&lt;/h2&gt;&lt;p&gt;Actual results of requests to the protected pages.&lt;/p&gt;&lt;/div&gt;&lt;span className="outline-tag"&gt;SERVER CHECKED&lt;/span&gt;&lt;/div&gt;</code> | Shows the permissions heading, explanation, and SERVER CHECKED tag. The heading's id provides the section's accessible label. |
| 55 | <code>&lt;div className="table-wrap"&gt;&lt;table className="permissions-table"&gt;</code> | Opens a horizontally scrollable wrapper and the actual HTML table. |
| 56 | <code>&lt;thead&gt;&lt;tr&gt;&lt;th scope="col"&gt;Workspace&lt;/th&gt;&lt;th scope="col"&gt;Your access&lt;/th&gt;&lt;th scope="col"&gt;Server response&lt;/th&gt;&lt;/tr&gt;&lt;/thead&gt;</code> | Defines the table's three column headers. scope=col identifies them as column headers for assistive technology. |
| 57 | <code>&lt;tbody&gt;{workspaces.map(workspace =&gt; {</code> | Starts the table body and maps the fixed workspaces into one table row each. |
| 58 | <code>const result = results.find(item =&gt; item.role === workspace.role);</code> | Finds the recorded request result for the row's workspace role. |
| 59 | <code>const allowed = result?.status === 200;</code> | Computes allowed as true only when this row's normalized result status is 200. |
| 60 | <code>const denied = result?.status === 403;</code> | Computes denied as true only for HTTP 403. Other statuses and missing results receive the failed-check presentation. |
| 61 | <code>return &lt;tr key={workspace.role}&gt;&lt;th scope="row"&gt;{workspace.label}&lt;/th&gt;&lt;td&gt;&lt;span className={&#96;permission-state ${allowed ? 'allowed' : denied ? 'denied' : ''}&#96;}&gt;{busy ? &lt;LoaderCircle size={14} className="spin" /&gt; : allowed ? &lt;CheckCircle2 size={14} /&gt; : denied ? &lt;LockKeyhole size={14} /&gt; : null}{busy ? 'Checking' : allowed ? 'Allowed' : denied ? 'Denied by server' : 'Check failed'}&lt;/span&gt;&lt;/td&gt;&lt;td&gt;{busy ? 'Waiting…' : result?.status ? &#96;HTTP ${result.status}&#96; : 'Server unavailable'}&lt;/td&gt;&lt;/tr&gt;;</code> | Returns a keyed row with a row header, state badge, and response text. Nested conditional expressions choose loading, allowed, denied, or failed labels and icons; classes select matching colors. A known status is displayed as HTTP plus its number; a missing status is shown as Server unavailable. |
| 62 | <code>})}&lt;/tbody&gt;</code> | Closes the map expression and table body. |
| 63 | <code>&lt;/table&gt;&lt;/div&gt;</code> | Closes the table and overflow wrapper. |
| 64 | <code>{!busy &amp;&amp; results.some(result =&gt; result.status !== 200 &amp;&amp; result.status !== 403) &amp;&amp; &lt;p className="error-box panel-error" role="alert"&gt;One or more permission checks could not complete. Check the server and try again.&lt;/p&gt;}</code> | After loading, shows an accessible error alert if any result is neither 200 nor 403, such as a network failure or unexpected HTTP status. |
| 65 | <code>&lt;p className="panel-note"&gt;Only your permitted workspace and account page appear in navigation. These pages demonstrate role access for ResQ Week 1 scope.&lt;/p&gt;</code> | Shows a scope note explaining that navigation contains the role's workspace and account page, and that this is a Week 1 access demonstration. |
| 66 | <code>&lt;/section&gt;</code> | Closes the permissions panel. |
| 67 | <code>&lt;/&gt;</code> | Closes the fragment. |
| 68 | <code>);</code> | Closes the JSX return expression. |
| 69 | <code>}</code> | Ends PermissionsWorkspace. |
| 71 | <code>function Account({ user }) {</code> | Defines Account and extracts the verified user prop. It does not make an additional profile request itself. |
| 72 | <code>return (</code> | Starts Account's JSX return. |
| 73 | <code>&lt;&gt;</code> | Opens a fragment so its heading and panel can be siblings. |
| 74 | <code>&lt;div className="page-heading"&gt;&lt;div&gt;&lt;span className="eyebrow"&gt;ACCOUNT DETAILS&lt;/span&gt;&lt;h1&gt;My account&lt;/h1&gt;&lt;p&gt;Your profile comes from the authenticated backend session.&lt;/p&gt;&lt;/div&gt;&lt;/div&gt;</code> | Displays the account heading and explains that the profile came from the authenticated backend. |
| 75 | <code>&lt;section className="panel account-panel" aria-labelledby="account-heading"&gt;</code> | Opens the account panel and labels it with the account-heading element. |
| 76 | <code>&lt;div className="panel-heading"&gt;&lt;div&gt;&lt;h2 id="account-heading"&gt;Signed-in profile&lt;/h2&gt;&lt;p&gt;The server owns your identity and role.&lt;/p&gt;&lt;/div&gt;&lt;UserRound size={23} /&gt;&lt;/div&gt;</code> | Displays the profile panel title, its explanation, and the user icon. |
| 77 | <code>&lt;dl className="account-facts"&gt;</code> | Opens a description list, the semantic HTML structure for labeled facts. |
| 78 | <code>&lt;div&gt;&lt;dt&gt;Full name&lt;/dt&gt;&lt;dd&gt;{user.full_name}&lt;/dd&gt;&lt;/div&gt;</code> | Adds the full-name label (dt) and value (dd) from user.full_name. |
| 79 | <code>&lt;div&gt;&lt;dt&gt;Email address&lt;/dt&gt;&lt;dd&gt;{user.email}&lt;/dd&gt;&lt;/div&gt;</code> | Adds the email label and user.email value. |
| 80 | <code>&lt;div&gt;&lt;dt&gt;Role&lt;/dt&gt;&lt;dd&gt;{roleLabel(user.role)}&lt;/dd&gt;&lt;/div&gt;</code> | Adds the role label and displays it through roleLabel. |
| 81 | <code>&lt;div&gt;&lt;dt&gt;User ID&lt;/dt&gt;&lt;dd&gt;{user.id}&lt;/dd&gt;&lt;/div&gt;</code> | Adds the backend user id. |
| 82 | <code>{user.team_id &amp;&amp; &lt;div&gt;&lt;dt&gt;Team ID&lt;/dt&gt;&lt;dd&gt;{user.team_id}&lt;/dd&gt;&lt;/div&gt;}</code> | Adds a team id only when user.team_id is truthy. A missing or falsy value produces no team row. |
| 83 | <code>&lt;/dl&gt;</code> | Closes the description list. |
| 84 | <code>&lt;p className="panel-note"&gt;Public registration creates citizen accounts. Admin and response team roles are provisioned by the local administrator.&lt;/p&gt;</code> | Shows the provisioning note: public registrations create citizens; privileged roles are created locally by the administrator. |
| 85 | <code>&lt;/section&gt;</code> | Closes the account panel. |
| 86 | <code>&lt;/&gt;</code> | Closes the fragment. |
| 87 | <code>);</code> | Closes Account's JSX return. |
| 88 | <code>}</code> | Ends Account. |
| 90 | <code>export default function App() {</code> | Defines and exports App, the root application component imported by main.jsx. |
| 91 | <code>const [user, setUser] = useState(null);</code> | Starts user as null. App renders Login until a backend profile is accepted into this state. |
| 92 | <code>const [booting, setBooting] = useState(Boolean(readSession()));</code> | Starts booting as the boolean result of reading a saved tab session. A saved session triggers the startup verification screen; no saved session initially allows the sign-in screen. |
| 93 | <code>const [bootError, setBootError] = useState('');</code> | Stores an initially empty startup error message, used when session verification cannot reach or complete against the server. |
| 94 | <code>const [bootAttempt, setBootAttempt] = useState(0);</code> | Stores a startup retry counter whose changes rerun the profile-verification effect. |
| 95 | <code>const [view, setView] = useState('workspace');</code> | Sets the initial local page selection to workspace; the other supported view is account. |
| 96 | <code>const [notice, setNotice] = useState('');</code> | Stores a notice shown on the unauthenticated Login screen, such as expiration or sign-out feedback. |
| 97 | <code>const [loggingOut, setLoggingOut] = useState(false);</code> | Tracks a pending logout so its button can be disabled and show a spinner. |
| 99 | <code>useEffect(() =&gt; {</code> | Starts the effect that installs a window listener for the custom session-expiration event. |
| 100 | <code>function expireSession() {</code> | Defines the listener that handles the API helper's expiration announcement. |
| 101 | <code>clearSession();</code> | Removes the saved tab session. |
| 102 | <code>setUser(null);</code> | Clears the authenticated user, causing the next render to show Login. |
| 103 | <code>setNotice('Your session has expired. Please sign in again.');</code> | Stores a sign-in-again notice for the Login screen. |
| 104 | <code>}</code> | Ends the listener function. |
| 105 | <code>window.addEventListener(SESSION_EXPIRED_EVENT, expireSession);</code> | Registers the listener on this browser window using the shared event name. |
| 106 | <code>return () =&gt; window.removeEventListener(SESSION_EXPIRED_EVENT, expireSession);</code> | Returns cleanup that removes precisely that listener when App unmounts or the development lifecycle reruns it. |
| 107 | <code>}, []);</code> | Uses an empty dependency list, meaning the subscription is associated with mounting rather than ordinary state changes. |
| 109 | <code>useEffect(() =&gt; {</code> | Starts the effect that verifies a saved session using the backend profile endpoint. |
| 110 | <code>if (!readSession()) { setBooting(false); return undefined; }</code> | When no readable session exists, ends startup loading and exits the effect without registering cleanup. |
| 111 | <code>const controller = new AbortController();</code> | Creates a controller to cancel this verification request during cleanup. |
| 112 | <code>setBooting(true);</code> | Shows the startup loading state for this verification attempt. |
| 113 | <code>setBootError('');</code> | Clears any previous startup error before trying again. |
| 114 | <code>api('/api/users/me', { signal: controller.signal })</code> | Requests /api/users/me with the saved bearer token and the controller's signal. |
| 115 | <code>.then(profile =&gt; { saveSession({ ...readSession(), user: profile }); setUser(profile); setView('workspace'); })</code> | On success, replaces the stored user information with the server profile, sets authenticated user state, and selects the workspace view. The spread preserves the saved session's other fields. |
| 116 | <code>.catch(error =&gt; {</code> | Starts the handler for an unsuccessful startup verification. |
| 117 | <code>if (error.name === 'AbortError') return;</code> | Ignores cancellation, since an aborted effect should not show a new error. |
| 118 | <code>if (error.status === 401 &#124;&#124; error.status === 403) {</code> | Checks whether the server refused authentication or access with 401 or 403. |
| 119 | <code>clearSession(); setNotice('Your session has expired. Please sign in again.');</code> | For those refusals, clears the session and sets the expiration notice, allowing a fresh sign-in after booting ends. |
| 120 | <code>} else setBootError(error.message);</code> | For other failures, stores error.message in bootError so App shows its reconnect/retry screen instead of silently discarding the session. |
| 121 | <code>})</code> | Closes the error handler. |
| 122 | <code>.finally(() =&gt; { if (!controller.signal.aborted) setBooting(false); });</code> | Ends startup loading when the request settles, provided the effect has not been canceled. |
| 123 | <code>return () =&gt; controller.abort();</code> | Returns cleanup that cancels the profile request. |
| 124 | <code>}, [bootAttempt]);</code> | Reruns verification when bootAttempt changes. Normal changes to user or view do not rerun this effect. |
| 126 | <code>async function login(session) {</code> | Defines the async callback passed to Login. Its argument is the authentication response returned by registration or sign-in. |
| 127 | <code>saveSession(session);</code> | Saves that session first so the next API request can read its access token. |
| 128 | <code>try {</code> | Starts verification of the freshly issued session. |
| 129 | <code>const profile = await api('/api/users/me');</code> | Fetches the authenticated backend profile. The API helper adds the token from the session just saved. |
| 130 | <code>saveSession({ ...session, user: profile });</code> | Saves the original session plus the freshly verified profile, replacing its user field. |
| 131 | <code>setUser(profile);</code> | Sets authenticated user state so the signed-in interface renders. |
| 132 | <code>setView('workspace');</code> | Opens the workspace view after successful authentication. |
| 133 | <code>setNotice('');</code> | Clears old sign-out/expiration notices. |
| 134 | <code>} catch (error) {</code> | Handles failure while verifying the newly issued session. |
| 135 | <code>clearSession();</code> | Removes the session so an unverified sign-in cannot remain stored. |
| 136 | <code>throw error;</code> | Rethrows the failure so Login's submit handler can display it. |
| 137 | <code>}</code> | Closes the login try/catch block. |
| 138 | <code>}</code> | Ends the login callback. |
| 140 | <code>async function logout() {</code> | Defines the async sign-out handler. |
| 141 | <code>setLoggingOut(true);</code> | Marks sign-out as pending, disabling the logout button. |
| 142 | <code>let message = 'You have signed out. Your server session has been revoked.';</code> | Prepares the success notice stating that the backend session was revoked; this remains the message if the logout request succeeds. |
| 143 | <code>try { await api('/api/auth/logout', { method: 'POST' }); }</code> | POSTs to /api/auth/logout with the current bearer token and awaits the backend response. |
| 144 | <code>catch (error) { message = &#96;You have signed out on this device. The server could not confirm session revocation: ${error.message}&#96;; }</code> | If the request fails, changes the notice to say the device was signed out but server revocation could not be confirmed, including the request error. |
| 145 | <code>finally { clearSession(); setUser(null); setNotice(message); setLoggingOut(false); }</code> | Always clears tab storage and authenticated user state, stores the selected notice, and resets loggingOut. Local sign-out therefore completes even if the backend request fails. |
| 146 | <code>}</code> | Ends logout. |
| 148 | <code>function navigate(next) {</code> | Defines navigation for the two local views. |
| 149 | <code>setView(next);</code> | Updates the selected view state. This switches components without updating the browser URL/history. |
| 150 | <code>window.scrollTo({ top: 0, behavior: 'instant' });</code> | Scrolls the window to the top immediately after a navigation choice. |
| 151 | <code>}</code> | Ends navigate. |
| 153 | <code>if (booting) return &lt;main className="startup-state"&gt;&lt;span className="brand-symbol"&gt;&lt;Waves /&gt;&lt;/span&gt;&lt;LoaderCircle className="spin" size={24} /&gt;&lt;p&gt;Verifying your session…&lt;/p&gt;&lt;/main&gt;;</code> | Returns only the startup loading screen while booting, including branding, a spinner, and session-verification text. Later return branches are skipped. |
| 154 | <code>if (bootError) return &lt;main className="startup-state"&gt;&lt;span className="brand-symbol"&gt;&lt;Waves /&gt;&lt;/span&gt;&lt;h1&gt;Reconnect your workspace.&lt;/h1&gt;&lt;p className="error-box" role="alert"&gt;{bootError}&lt;/p&gt;&lt;div className="button-row"&gt;&lt;button className="button primary" onClick={() =&gt; setBootAttempt(value =&gt; value + 1)}&gt;Try again&lt;ArrowRight size={17} /&gt;&lt;/button&gt;&lt;button className="button secondary" onClick={() =&gt; { clearSession(); setBootError(''); }}&gt;Sign in again&lt;/button&gt;&lt;/div&gt;&lt;/main&gt;;</code> | Returns the reconnect screen if bootError is nonempty. Try again increments bootAttempt; Sign in again clears stored session and the error, leading to Login. The error paragraph has role=alert. |
| 155 | <code>if (!user) return &lt;Login onLogin={login} notice={notice} /&gt;;</code> | When there is no authenticated user, returns Login with the login callback and current notice. |
| 157 | <code>const initials = user.full_name.split(' ').filter(Boolean).map(part =&gt; part[0]).slice(0, 2).join('').toUpperCase();</code> | Builds the avatar initials from the first letters of the first two nonempty name parts, then joins and uppercases them. |
| 158 | <code>const links = [{ id: 'workspace', label: &#96;${roleLabel(user.role)} workspace&#96;, icon: LayoutDashboard }, { id: 'account', label: 'My account', icon: UserRound }];</code> | Defines exactly two navigation links: the user's role-specific workspace and My account. Each entry includes an id, friendly label, and icon component. |
| 159 | <code>return (</code> | Starts the authenticated layout's JSX return. |
| 160 | <code>&lt;div className="app-shell"&gt;</code> | Opens the top-level application shell. |
| 161 | <code>&lt;a className="skip-link" href="#main-content"&gt;Skip to content&lt;/a&gt;</code> | Provides a keyboard skip link to the main-content element, helping users bypass repeated navigation. |
| 162 | <code>&lt;aside className="sidebar"&gt;</code> | Opens the sidebar containing branding, navigation, and profile controls. |
| 163 | <code>&lt;a className="brand" href="#" onClick={event =&gt; { event.preventDefault(); navigate('workspace'); }}&gt;&lt;span className="brand-symbol"&gt;&lt;Waves size={25} /&gt;&lt;/span&gt;&lt;span&gt;ResQ &lt;strong&gt;Kerala&lt;/strong&gt;&lt;small&gt;RESQ · WEEK 1&lt;/small&gt;&lt;/span&gt;&lt;/a&gt;</code> | Displays the ResQ Kerala brand link. Its click handler prevents the default hash jump and selects the workspace through navigate. |
| 164 | <code>&lt;div className="workspace-pill"&gt;&lt;ShieldCheck size={14} /&gt;{roleLabel(user.role)} account&lt;/div&gt;</code> | Displays a pill with the friendly role and shield icon; this is descriptive UI, not an access-control decision. |
| 165 | <code>&lt;div className="navigation-label"&gt;YOUR WORKSPACE&lt;/div&gt;</code> | Shows the fixed navigation group label. |
| 166 | <code>&lt;nav aria-label="Main navigation"&gt;{links.map(link =&gt; &lt;button type="button" key={link.id} onClick={() =&gt; navigate(link.id)} className={view === link.id ? 'nav-link active' : 'nav-link'} aria-current={view === link.id ? 'page' : undefined}&gt;&lt;link.icon size={19} /&gt;&lt;span&gt;{link.label}&lt;/span&gt;&lt;/button&gt;)}&lt;/nav&gt;</code> | Maps the two link entries into buttons. Each button switches local view, uses an active class and aria-current=page when selected, and renders the entry's icon component dynamically. |
| 167 | <code>&lt;div className="sidebar-bottom"&gt;</code> | Opens the bottom sidebar area, pushed down by its stylesheet. |
| 168 | <code>&lt;div className="foundation-card"&gt;&lt;span className="eyebrow light"&gt;RESQ · WEEK 1&lt;/span&gt;&lt;p&gt;Authentication.&lt;br /&gt;Role permissions.&lt;/p&gt;&lt;span&gt;Local demonstration&lt;/span&gt;&lt;/div&gt;</code> | Displays a static scope card describing this local authentication/permissions demonstration. |
| 169 | <code>&lt;div className="profile-block"&gt;&lt;span className="avatar"&gt;{initials}&lt;/span&gt;&lt;span className="profile-name"&gt;&lt;strong&gt;{user.full_name}&lt;/strong&gt;&lt;small&gt;{roleLabel(user.role)}&lt;/small&gt;&lt;/span&gt;&lt;button className="logout-button" type="button" onClick={logout} disabled={loggingOut} aria-label="Sign out"&gt;{loggingOut ? &lt;LoaderCircle size={18} className="spin" /&gt; : &lt;LogOut size={18} /&gt;}&lt;/button&gt;&lt;/div&gt;</code> | Shows initials, name, role, and the accessible sign-out button. During logout, the button is disabled and its icon changes to a spinning loader. |
| 170 | <code>&lt;/div&gt;</code> | Closes the sidebar's bottom area. |
| 171 | <code>&lt;/aside&gt;</code> | Closes the sidebar. |
| 172 | <code>&lt;div className="workspace"&gt;</code> | Opens the right-hand workspace container. |
| 173 | <code>&lt;header className="workspace-header"&gt;&lt;span&gt;ResQ &lt;span className="breadcrumb-divider"&gt;/&lt;/span&gt; {links.find(link =&gt; link.id === view)?.label}&lt;/span&gt;&lt;span className="week-tag"&gt;WEEK 1&lt;/span&gt;&lt;/header&gt;</code> | Shows a breadcrumb-like header computed from the current link label and a fixed WEEK 1 badge. Optional chaining tolerates a missing match. |
| 174 | <code>&lt;main id="main-content" className="workspace-main"&gt;{view === 'account' ? &lt;Account user={user} /&gt; : &lt;PermissionsWorkspace user={user} /&gt;}&lt;/main&gt;</code> | Provides the skip link's main-content target and renders Account when view is account; every other view value renders PermissionsWorkspace with the authenticated user. |
| 175 | <code>&lt;footer className="workspace-footer"&gt;&lt;span&gt;ResQ Kerala · ResQ&lt;/span&gt;&lt;span&gt;Authentication and role permissions demo&lt;/span&gt;&lt;/footer&gt;</code> | Displays the fixed project footer and scope description. |
| 176 | <code>&lt;/div&gt;</code> | Closes the workspace container. |
| 177 | <code>&lt;/div&gt;</code> | Closes the application shell. |
| 178 | <code>);</code> | Closes App's JSX return expression. |
| 179 | <code>}</code> | Ends App. |

### `frontend/src/components/shared/Login.jsx`

**Purpose:** Controlled sign-in and citizen-registration form.

Login keeps form fields in React state. Native input constraints run before a normal form submission; submit then normalizes email/name and POSTs to either register or login. The result is sent to App.onLogin, which saves the session and verifies /api/users/me. Any request or verification error is shown in the form. Changing form mode clears the password and error while preserving email and full name.

**Coverage:** 82 physical lines; 78 nonblank lines explained; 4 blank lines are readability separators.

| Line | Code | Explanation |
| --- | --- | --- |
| 1 | <code>import { useState } from 'react';</code> | Imports useState for the form's mode, input values, error, and pending state. |
| 2 | <code>import { ArrowRight, Check, LoaderCircle, ShieldCheck, Waves } from 'lucide-react';</code> | Imports five Lucide SVG icons used in the form, branding, and decorative checklist. |
| 3 | <code>import { api } from '../../services/api';</code> | Imports the shared request helper through the relative path two folders up. |
| 5 | <code>export default function Login({ onLogin, notice = '' }) {</code> | Defines and exports Login, receiving the parent onLogin callback and a notice prop that defaults to an empty string. |
| 6 | <code>const [mode, setMode] = useState('login');</code> | Starts the mode at login; register selects citizen registration instead. |
| 7 | <code>const [fullName, setFullName] = useState('');</code> | Stores the full name as a controlled input value, initially empty. |
| 8 | <code>const [email, setEmail] = useState('');</code> | Stores the email as a controlled input value, initially empty. |
| 9 | <code>const [password, setPassword] = useState('');</code> | Stores the password as a controlled input value, initially empty. |
| 10 | <code>const [error, setError] = useState('');</code> | Stores the current form error message, initially empty. |
| 11 | <code>const [busy, setBusy] = useState(false);</code> | Tracks whether submission/parent verification is pending, initially false. |
| 13 | <code>async function submit(event) {</code> | Defines the asynchronous form submission event handler. |
| 14 | <code>event.preventDefault();</code> | Prevents the browser's ordinary form navigation/reload so React can handle submission. |
| 15 | <code>setError('');</code> | Clears the previous submission error. |
| 16 | <code>setBusy(true);</code> | Marks the form busy, disabling fields, mode buttons, and the submit button. |
| 17 | <code>try {</code> | Begins the operation whose failures will be caught and displayed. |
| 18 | <code>const credentials = { email: email.trim().toLowerCase(), password };</code> | Builds credentials with surrounding email whitespace removed and email lowercased. The password is preserved exactly, including any spaces. |
| 19 | <code>const session = mode === 'register'</code> | Starts a conditional expression choosing the backend endpoint according to mode. |
| 20 | <code>? await api('/api/auth/register', { method: 'POST', body: { ...credentials, full_name: fullName.trim() } })</code> | In registration mode, POSTs credentials plus trimmed full_name to /api/auth/register. The shared helper serializes the body as JSON; no role field is supplied by the public form. |
| 21 | <code>: await api('/api/auth/login', { method: 'POST', body: credentials });</code> | Otherwise POSTs the email/password credentials to /api/auth/login. |
| 22 | <code>await onLogin(session);</code> | Awaits App's onLogin callback so the UI waits for the authenticated profile to be verified as well as the initial auth request. |
| 23 | <code>} catch (failure) {</code> | Catches either the authentication request failure or the parent callback's rethrown verification failure. |
| 24 | <code>setError(failure.message);</code> | Copies the error message into form state for the alert paragraph. |
| 25 | <code>} finally {</code> | Begins cleanup that runs whether the operation succeeded or failed. |
| 26 | <code>setBusy(false);</code> | Clears busy so controls return to their normal state if this form is still displayed. |
| 27 | <code>}</code> | Closes the try/catch/finally block. |
| 28 | <code>}</code> | Ends submit. |
| 30 | <code>function changeMode(next) {</code> | Defines the handler for selecting sign-in or registration mode. |
| 31 | <code>setMode(next);</code> | Changes mode to the supplied value. |
| 32 | <code>setError('');</code> | Clears an old error that might belong to the other form mode. |
| 33 | <code>setPassword('');</code> | Clears the password when changing modes; email/fullName are retained because they are not reset here. |
| 34 | <code>}</code> | Ends changeMode. |
| 36 | <code>return (</code> | Starts returning the authentication page JSX. |
| 37 | <code>&lt;main className="auth-layout"&gt;</code> | Opens the main authentication layout, arranged by CSS as an explanatory area and form area. |
| 38 | <code>&lt;section className="auth-story" aria-label="ResQ Week 1 work"&gt;</code> | Opens the explanatory story section and labels it for assistive technology. |
| 39 | <code>&lt;a className="brand auth-brand" href="#" aria-label="ResQ Kerala home"&gt;</code> | Starts the brand anchor with a home label. Unlike App's brand anchor, this anchor has no custom click handler and its href is the page hash. |
| 40 | <code>&lt;span className="brand-symbol"&gt;&lt;Waves size={26} /&gt;&lt;/span&gt;</code> | Displays the waves icon in the brand symbol box. |
| 41 | <code>&lt;span&gt;ResQ &lt;strong&gt;Kerala&lt;/strong&gt;&lt;small&gt;RESQ · WEEK 1&lt;/small&gt;&lt;/span&gt;</code> | Displays the ResQ Kerala brand text and the ResQ Week 1 sublabel. |
| 42 | <code>&lt;/a&gt;</code> | Closes the brand anchor. |
| 43 | <code>&lt;div className="story-copy"&gt;</code> | Opens the story text container. |
| 44 | <code>&lt;span className="eyebrow light"&gt;AUTHENTICATION &amp; ROLE ACCESS&lt;/span&gt;</code> | Shows the small authentication/role-access label. |
| 45 | <code>&lt;h1&gt;The right access.&lt;br /&gt;For every account.&lt;/h1&gt;</code> | Shows the story heading with an explicit line break, which CSS hides on small screens. |
| 46 | <code>&lt;p&gt;ResQ first-week foundation: account creation, secure sign-in, sign-out, and access controlled by the server.&lt;/p&gt;</code> | Describes account creation, sign-in, sign-out, and server-controlled access as the demonstration's scope. |
| 47 | <code>&lt;div className="story-steps"&gt;</code> | Opens the checklist container. |
| 48 | <code>{['Create a citizen account', 'Sign in to your role', 'Verify workspace permissions'].map((step, index) =&gt; (</code> | Maps three fixed explanatory step strings to JSX; the callback receives each step and its zero-based index. |
| 49 | <code>&lt;div key={step}&gt;&lt;span&gt;{String(index + 1).padStart(2, '0')}&lt;/span&gt;{step}&lt;Check size={15} /&gt;&lt;/div&gt;</code> | Creates a keyed row displaying a two-digit step number, the text, and a check icon. String plus padStart produces 01, 02, and 03. |
| 50 | <code>))}</code> | Closes the map callback and JSX expression. |
| 51 | <code>&lt;/div&gt;</code> | Closes the checklist. |
| 52 | <code>&lt;/div&gt;</code> | Closes story-copy. |
| 53 | <code>&lt;svg className="contour-art" viewBox="0 0 600 400" aria-hidden="true"&gt;</code> | Opens a decorative SVG with its internal coordinate system. aria-hidden prevents decorative paths being announced by screen readers. |
| 54 | <code>{[0, 1, 2, 3, 4, 5, 6, 7].map(index =&gt; &lt;path key={index} d={&#96;M -50 ${140 + index * 28} C 90 ${-30 + index * 33}, 240 ${370 + index * 12}, 650 ${100 + index * 37}&#96;} /&gt;)}</code> | Maps eight indexes to curved SVG paths. The template string calculates start/control/end coordinates for each curve, creating the repeated contour decoration; key keeps each React element identifiable. |
| 55 | <code>&lt;/svg&gt;</code> | Closes the SVG. |
| 56 | <code>&lt;p className="story-footer"&gt;ResQ Kerala · Member-specific foundation&lt;/p&gt;</code> | Shows the story's fixed scope footer. |
| 57 | <code>&lt;/section&gt;</code> | Closes the explanatory section. |
| 58 | <code>&lt;section className="auth-main"&gt;</code> | Opens the section containing the sign-in/registration interface. |
| 59 | <code>&lt;div className="auth-topline"&gt;&lt;ShieldCheck size={17} /&gt;&lt;span&gt;Authentication and role permissions&lt;/span&gt;&lt;/div&gt;</code> | Shows the shield icon and authentication/permissions topline. |
| 60 | <code>&lt;div className="auth-card"&gt;</code> | Opens the auth-card that centers and constrains the form area. |
| 61 | <code>&lt;span className="eyebrow"&gt;RESQ · WEEK 1&lt;/span&gt;</code> | Displays the ResQ Week 1 eyebrow label. |
| 62 | <code>&lt;h2&gt;{mode === 'login' ? 'Welcome to your workspace.' : 'Create your account.'}&lt;/h2&gt;</code> | Selects the card heading from the current mode. |
| 63 | <code>&lt;p className="auth-intro"&gt;{mode === 'login' ? 'Sign in to verify your account and open the workspace allowed for your role.' : 'Register as a citizen. Your permissions are assigned by the server.'}&lt;/p&gt;</code> | Selects explanatory text from the mode; registration explicitly says the new account is a citizen and the server assigns permissions. |
| 64 | <code>&lt;div className="auth-tabs" aria-label="Account access"&gt;</code> | Opens the two mode buttons with an accessible group label. |
| 65 | <code>&lt;button type="button" className={mode === 'login' ? 'active' : ''} aria-pressed={mode === 'login'} onClick={() =&gt; changeMode('login')} disabled={busy}&gt;Sign in&lt;/button&gt;</code> | Shows the sign-in mode button. Its selected class and aria-pressed value follow mode; it calls changeMode and is disabled while busy. type=button avoids submitting a form. |
| 66 | <code>&lt;button type="button" className={mode === 'register' ? 'active' : ''} aria-pressed={mode === 'register'} onClick={() =&gt; changeMode('register')} disabled={busy}&gt;Create account&lt;/button&gt;</code> | Shows the registration mode button with the same state-driven selection, accessible pressed state, and busy disabling. |
| 67 | <code>&lt;/div&gt;</code> | Closes the mode-button container. |
| 68 | <code>{notice &amp;&amp; &lt;p className="notice" role="status"&gt;{notice}&lt;/p&gt;}</code> | Displays the parent's notice only when nonempty. role=status presents nonurgent sign-out/expiration feedback to assistive technology. |
| 69 | <code>&lt;form onSubmit={submit} className="auth-form"&gt;</code> | Opens the form and connects its submit event to the custom async handler. |
| 70 | <code>{mode === 'register' &amp;&amp; &lt;label&gt;Full name&lt;input type="text" value={fullName} onChange={event =&gt; setFullName(event.target.value)} autoComplete="name" required minLength={3} maxLength={100} placeholder="How should we address you?" disabled={busy} /&gt;&lt;/label&gt;}</code> | Only registration shows the controlled full-name input. onChange copies the typed value into state; browser constraints require 3-100 characters, autocomplete identifies a person's name, and busy disables editing. |
| 71 | <code>&lt;label&gt;Email address&lt;input type="email" value={email} onChange={event =&gt; setEmail(event.target.value)} autoComplete="username" required maxLength={254} placeholder="you@example.com" disabled={busy} /&gt;&lt;/label&gt;</code> | Shows the controlled email input, with email-format checking, required/maxLength constraints, username autocomplete, and busy disabling. |
| 72 | <code>&lt;label&gt;Password&lt;input type="password" value={password} onChange={event =&gt; setPassword(event.target.value)} autoComplete={mode === 'register' ? 'new-password' : 'current-password'} required minLength={mode === 'register' ? 10 : undefined} maxLength={128} placeholder={mode === 'register' ? 'At least 10 characters' : 'Enter your password'} disabled={busy} /&gt;&lt;/label&gt;</code> | Shows the controlled masked password input. Registration requests new-password autocomplete and a minimum of 10 characters; login requests current-password and has no minlength here. Both require input and limit it to 128 characters. The placeholder and disabled state depend on mode/busy. |
| 73 | <code>{error &amp;&amp; &lt;p className="error-box" role="alert"&gt;{error}&lt;/p&gt;}</code> | Displays the current submission error only when nonempty; role=alert makes the failure accessible. |
| 74 | <code>&lt;button className="button primary auth-submit" type="submit" disabled={busy}&gt;{busy ? &lt;&gt;&lt;LoaderCircle className="spin" size={18} /&gt;{mode === 'register' ? 'Creating your account…' : 'Signing in…'}&lt;/&gt; : &lt;&gt;{mode === 'register' ? 'Create citizen account' : 'Sign in'}&lt;ArrowRight size={18} /&gt;&lt;/&gt;}&lt;/button&gt;</code> | Shows the submit button with conditional fragments: while busy, a spinner and mode-specific progress text; otherwise, mode-specific action text and an arrow. disabled prevents repeated submissions. |
| 75 | <code>&lt;/form&gt;</code> | Closes the form. |
| 76 | <code>&lt;p className="auth-help"&gt;{mode === 'register' ? 'Admin and response team accounts are created by the local setup script.' : 'Demo credentials are generated locally. See README.md and .runtime/demo-accounts.json.'}&lt;/p&gt;</code> | Displays mode-specific setup guidance. The login text points to README and a private local demo-account file; it does not read that file or put credentials into this source. |
| 77 | <code>&lt;/div&gt;</code> | Closes auth-card. |
| 78 | <code>&lt;div className="prototype-note"&gt;&lt;span className="outline-tag"&gt;WEEK 1 AUTH DEMO&lt;/span&gt; ResQ authentication and permissions tasks&lt;/div&gt;</code> | Shows the static WEEK 1 AUTH DEMO scope note below the card. |
| 79 | <code>&lt;/section&gt;</code> | Closes auth-main. |
| 80 | <code>&lt;/main&gt;</code> | Closes the main authentication layout. |
| 81 | <code>);</code> | Closes the JSX return expression. |
| 82 | <code>}</code> | Ends Login. |

### `frontend/src/services/api.js`

**Purpose:** Tab-session storage and JSON HTTP request helper.

Both Login and App call this helper using same-origin relative paths. Vite proxies those paths to the local backend. A readable stored session contributes its access token as a Bearer Authorization header. The helper converts server failures into Error objects with HTTP status and readable detail, and announces an expired authenticated session to App. sessionStorage belongs to the current origin/tab and survives reloads; this code does not implement refresh tokens or cross-tab synchronization.

**Coverage:** 55 physical lines; 51 nonblank lines explained; 4 blank lines are readability separators.

| Line | Code | Explanation |
| --- | --- | --- |
| 1 | <code>export const SESSION_KEY = 'resq-week1-session';</code> | Exports the browser sessionStorage key under which the authentication response is serialized. |
| 2 | <code>export const SESSION_EXPIRED_EVENT = 'resq:session-expired';</code> | Exports the custom event name used to coordinate session expiration inside the current browser window. |
| 4 | <code>export function readSession() {</code> | Defines and exports the function that reads a usable stored session. |
| 5 | <code>try {</code> | Starts error handling around browser storage access and JSON parsing. |
| 6 | <code>const value = JSON.parse(sessionStorage.getItem(SESSION_KEY) &#124;&#124; 'null');</code> | Reads the stored string and parses it. When the key is missing, the fallback string null parses to JavaScript null. |
| 7 | <code>return value?.access_token &amp;&amp; value?.user ? value : null;</code> | Accepts the parsed object only if access_token and user are truthy. Optional chaining tolerates null; this is a presence check, not a token/signature/role validation. |
| 8 | <code>} catch {</code> | Handles invalid JSON or another error encountered while reading/parsing storage. |
| 9 | <code>sessionStorage.removeItem(SESSION_KEY);</code> | Deletes the bad stored value. Storage deletion itself is not wrapped in a second try, so browsers denying storage access can still throw here. |
| 10 | <code>return null;</code> | Returns null to indicate no usable session after cleanup. |
| 11 | <code>}</code> | Closes the catch block. |
| 12 | <code>}</code> | Ends readSession. |
| 14 | <code>export function saveSession(session) {</code> | Defines and exports saveSession. |
| 15 | <code>sessionStorage.setItem(SESSION_KEY, JSON.stringify(session));</code> | Serializes the supplied session as JSON and stores it for this browser origin/tab. The access token is stored in JavaScript-accessible storage; this function neither encrypts it nor validates its shape. |
| 16 | <code>}</code> | Ends saveSession. Storage write errors are not caught inside this function. |
| 18 | <code>export function clearSession() {</code> | Defines and exports clearSession. |
| 19 | <code>sessionStorage.removeItem(SESSION_KEY);</code> | Deletes the saved session key from this tab's browser storage. |
| 20 | <code>}</code> | Ends clearSession. |
| 22 | <code>export async function api(path, { method = 'GET', body, signal } = {}) {</code> | Defines the async request helper. Destructuring supplies GET by default and accepts body/signal; an omitted options argument defaults to an empty object. |
| 23 | <code>const token = readSession()?.access_token;</code> | Reads the current saved access token, using optional chaining when no session exists. |
| 24 | <code>let response;</code> | Declares response outside the try block so the later response-processing code can use it. |
| 25 | <code>try {</code> | Begins catching transport-level fetch failures. |
| 26 | <code>response = await fetch(path, {</code> | Calls browser fetch with the provided path and starts building its options object. Relative paths target the frontend's origin before Vite applies its proxy. |
| 27 | <code>method,</code> | Sets the HTTP method chosen by the caller or defaulted to GET. |
| 28 | <code>headers: {</code> | Starts the request-header object. |
| 29 | <code>...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),</code> | Adds Content-Type: application/json only when body is not undefined. The spread otherwise inserts no header fields. |
| 30 | <code>...(token ? { Authorization: &#96;Bearer ${token}&#96; } : {}),</code> | Adds Authorization: Bearer followed by the saved token only when a token exists. Template interpolation builds the header string. |
| 31 | <code>},</code> | Closes headers. |
| 32 | <code>...(body !== undefined ? { body: JSON.stringify(body) } : {}),</code> | Adds a JSON-serialized request body only when a body argument was supplied. Explicit null counts as supplied and becomes the JSON string null. |
| 33 | <code>signal,</code> | Passes through the optional AbortSignal so components can cancel their requests. |
| 34 | <code>});</code> | Closes the fetch call and awaits its HTTP response; fetch itself does not reject solely because the server returns 4xx or 5xx. |
| 35 | <code>} catch (error) {</code> | Catches network, fetch setup, or cancellation failures before a usable response is obtained. |
| 36 | <code>if (error.name === 'AbortError') throw error;</code> | Preserves AbortError unchanged so effect cleanup can recognize and ignore cancellation. |
| 37 | <code>throw new Error('Unable to reach the server. Check that the backend is running, then try again.');</code> | Replaces other transport failures with a friendly connection error. This error has no HTTP status because no accepted HTTP response exists. |
| 38 | <code>}</code> | Closes the transport catch block. |
| 39 | <code>const result = response.status === 204 ? null : await response.json().catch(() =&gt; null);</code> | Uses null for a 204 No Content response; otherwise tries parsing JSON and falls back to null if parsing fails. A successful non-JSON response is therefore returned as null rather than treated as an error. |
| 40 | <code>if (!response.ok) {</code> | Starts error conversion when response.ok is false; response.ok represents HTTP success in the 200-299 range. |
| 41 | <code>let message = 'The request could not be completed. Please try again.';</code> | Prepares a generic error message for failures lacking a recognized detail format. |
| 42 | <code>if (typeof result?.detail === 'string') message = result.detail;</code> | When server detail is a string, uses that string directly as the message. |
| 43 | <code>else if (Array.isArray(result?.detail)) {</code> | When detail is an array, treats it as structured validation errors. |
| 44 | <code>message = result.detail.map(item =&gt; &#96;${item.loc?.slice(1).join(' ') &#124;&#124; 'Input'}: ${item.msg}&#96;).join('. ');</code> | Formats each validation item using its location (omitting the first component) and message, then joins them with sentence separators. Missing/empty locations fall back to Input. |
| 45 | <code>}</code> | Closes array-detail formatting. |
| 46 | <code>const error = new Error(message);</code> | Creates a JavaScript Error carrying the selected human-readable message. |
| 47 | <code>error.status = response.status;</code> | Attaches the response status to that Error so components can distinguish denied access, expired sessions, and other HTTP failures. |
| 48 | <code>if (response.status === 401 &amp;&amp; token &amp;&amp; !['/api/auth/login', '/api/auth/register', '/api/auth/logout'].includes(path)) {</code> | Recognizes expiration only for 401 when a token was sent, excluding login, register, and logout paths. A 403 workspace denial does not trigger this global expiration flow. |
| 49 | <code>clearSession();</code> | Removes the expired session from tab storage. |
| 50 | <code>window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));</code> | Dispatches the custom window event so App's registered listener clears its user state and shows a sign-in-again notice. |
| 51 | <code>}</code> | Closes the expiration condition. |
| 52 | <code>throw error;</code> | Throws the status-bearing Error so the calling component can display or classify the failure. |
| 53 | <code>}</code> | Closes HTTP error processing. |
| 54 | <code>return result;</code> | Returns the parsed JSON result (or null) for a successful HTTP response. |
| 55 | <code>}</code> | Ends api. |

### `frontend/src/styles.css`

**Purpose:** Global visual design, responsive layouts, and accessibility presentation.

Styles apply to className values in App and Login and to ordinary HTML elements. CSS selects elements and changes appearance/layout; it does not perform login or enforce permissions. The base layout uses a dark left panel/sidebar and light content area. Responsive blocks at 1600px, 1100px, 760px, and 580px adjust spacing and layout; the smallest block turns the sidebar into a top navigation bar. The reduced-motion block shortens animations/transitions. A px value is a CSS pixel; percentages refer to an applicable container, fr divides available grid space, and unitless line-height multiplies font size. Hex values specify colors; eight-digit hex includes an alpha/transparency channel. Logical inline spacing follows text direction.

**Coverage:** 227 physical lines; 227 nonblank lines explained; 0 blank lines are readability separators.

| Line | Code | Explanation |
| --- | --- | --- |
| 1 | <code>:root {</code> | Opens the root-element rule containing inherited text defaults, the page background, and reusable color variables. |
| 2 | <code>font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;</code> | Sets the ordered font fallback list to <code>&#x27;Segoe UI&#x27;, system-ui, -apple-system, sans-serif</code>. |
| 3 | <code>color: #203b40;</code> | Sets the foreground/text color to <code>#203b40</code>. |
| 4 | <code>background: #f5f6f2;</code> | Sets the background to <code>#f5f6f2</code>. |
| 5 | <code>font-synthesis: none;</code> | Disables artificially synthesized font styles such as fake bold/italic. |
| 6 | <code>text-rendering: optimizeLegibility;</code> | Requests legibility-focused text rendering. |
| 7 | <code>-webkit-font-smoothing: antialiased;</code> | Requests antialiased text smoothing in supporting WebKit-style implementations. |
| 8 | <code>--navy: #15353d;</code> | Defines the reusable custom property <code>--navy</code> as <code>#15353d</code>. |
| 9 | <code>--teal: #237c6b;</code> | Defines the reusable custom property <code>--teal</code> as <code>#237c6b</code>. |
| 10 | <code>--muted: #687b7c;</code> | Defines the reusable custom property <code>--muted</code> as <code>#687b7c</code>. |
| 11 | <code>--border: #e1e7e2;</code> | Defines the reusable custom property <code>--border</code> as <code>#e1e7e2</code>. |
| 12 | <code>}</code> | Closes the root-element defaults and color-variable rule. |
| 13 | <code>* { box-sizing: border-box; }</code> | Styles every element: includes padding and borders inside declared width/height. |
| 14 | <code>body { margin: 0; min-width: 320px; }</code> | Styles the document body: sets outer spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom; four: top/right/bottom/left) to <code>0</code>; sets the minimum width to <code>320px</code>. |
| 15 | <code>button, input { font: inherit; }</code> | Styles buttons and input fields: inherits the surrounding text font settings instead of browser control defaults. |
| 16 | <code>button, a, input { -webkit-tap-highlight-color: transparent; }</code> | Styles interactive buttons, links, and inputs: removes the browser tap highlight in supporting touch browsers. |
| 17 | <code>button { cursor: pointer; }</code> | Styles all buttons: shows the clickable hand cursor. |
| 18 | <code>button:disabled { cursor: wait; opacity: .6; }</code> | Styles disabled buttons: shows a waiting cursor; sets opacity to <code>.6</code>. |
| 19 | <code>button:focus-visible, a:focus-visible, input:focus-visible { outline: 3px solid #61baa4; outline-offset: 3px; }</code> | Styles keyboard-visible focus on buttons, links, and inputs: sets the focus outline to <code>3px solid #61baa4</code>; separates the outline from the box by <code>3px</code>. |
| 20 | <code>a { color: inherit; }</code> | Styles all links: sets the foreground/text color to <code>inherit</code>. |
| 21 | <code>h1, h2, p { margin: 0; }</code> | Styles headings and paragraphs: sets outer spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom; four: top/right/bottom/left) to <code>0</code>. |
| 22 | <code>h1 { font-size: 35px; font-weight: 600; letter-spacing: -.8px; }</code> | Styles top-level headings: sets text size to <code>35px</code>; sets font weight to <code>600</code>; sets space between letters to <code>-.8px</code>. |
| 23 | <code>h2 { font-size: 20px; font-weight: 600; }</code> | Styles second-level headings: sets text size to <code>20px</code>; sets font weight to <code>600</code>. |
| 24 | <code>.eyebrow { color: #6f8d78; font-size: 10px; font-weight: 650; letter-spacing: 1.65px; }</code> | Styles the small uppercase-style section labels: sets the foreground/text color to <code>#6f8d78</code>; sets text size to <code>10px</code>; sets font weight to <code>650</code>; sets space between letters to <code>1.65px</code>. |
| 25 | <code>.eyebrow.light { color: #9ebdb1; }</code> | Styles eyebrow labels using the light variant: sets the foreground/text color to <code>#9ebdb1</code>. |
| 26 | <code>.button { display: inline-flex; align-items: center; justify-content: center; gap: 9px; border: 1px solid transparent; border-radius: 8px; padding: 12px 17px; min-height: 44px; font-size: 12px; font-weight: 600; }</code> | Styles shared action buttons: uses an inline flex container for aligned text/icons; centers flex/grid children across the cross axis; centers children along the main axis; sets spacing between flex/grid children to <code>9px</code>; sets all four borders to <code>1px solid transparent</code>; rounds corners by <code>8px</code>; sets inner spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom) to <code>12px 17px</code>; sets the minimum height to <code>44px</code>; sets text size to <code>12px</code>; sets font weight to <code>600</code>. |
| 27 | <code>.button.primary { background: var(--teal); color: white; box-shadow: 0 4px 12px #237c6b18; }</code> | Styles primary action buttons: sets the background to <code>var(--teal)</code> using a custom property defined at the document root; sets the foreground/text color to <code>white</code>; sets the box shadow to (horizontal offset, vertical offset, blur, and color) <code>0 4px 12px #237c6b18</code>. |
| 28 | <code>.button.primary:hover { background: #176354; }</code> | Styles primary buttons under the pointer: sets the background to <code>#176354</code>. |
| 29 | <code>.button.secondary { color: #446458; background: white; border-color: #d7e1d4; }</code> | Styles secondary action buttons: sets the foreground/text color to <code>#446458</code>; sets the background to <code>white</code>; sets border color to <code>#d7e1d4</code>. |
| 30 | <code>.button.secondary:hover { background: #f0f5eb; }</code> | Styles secondary buttons under the pointer: sets the background to <code>#f0f5eb</code>. |
| 31 | <code>.button-row { display: flex; flex-wrap: wrap; gap: 10px; }</code> | Styles groups of action buttons: uses flexbox to arrange children; allows flex children to wrap onto additional lines; sets spacing between flex/grid children to <code>10px</code>. |
| 32 | <code>.brand { display: flex; align-items: center; gap: 11px; text-decoration: none; color: white; }</code> | Styles the brand link: uses flexbox to arrange children; centers flex/grid children across the cross axis; sets spacing between flex/grid children to <code>11px</code>; removes the default link underline; sets the foreground/text color to <code>white</code>. |
| 33 | <code>.brand-symbol { display: grid; place-items: center; width: 43px; height: 44px; background: #33514e; border: 1px solid #4f7062; color: #b6d6ab; border-radius: 12px; flex: none; }</code> | Styles the waves icon box: uses CSS grid to arrange children; centers grid content in both directions; sets width to <code>43px</code>; sets height to <code>44px</code>; sets the background to <code>#33514e</code>; sets all four borders to <code>1px solid #4f7062</code>; sets the foreground/text color to <code>#b6d6ab</code>; rounds corners by <code>12px</code>; prevents the item growing or shrinking in flex layout. |
| 34 | <code>.brand &gt; span:last-child { font-size: 23px; font-weight: 350; letter-spacing: -.7px; white-space: nowrap; }</code> | Styles the brand text span directly inside the brand link: sets text size to <code>23px</code>; sets font weight to <code>350</code>; sets space between letters to <code>-.7px</code>; keeps text on one line. |
| 35 | <code>.brand strong { font-weight: 650; }</code> | Styles the emphasized Kerala brand text: sets font weight to <code>650</code>. |
| 36 | <code>.brand small { display: block; color: #a0b8ab; font-size: 7px; font-weight: 600; letter-spacing: 2px; margin-top: 4px; }</code> | Styles the brand sublabel: displays the item as a block; sets the foreground/text color to <code>#a0b8ab</code>; sets text size to <code>7px</code>; sets font weight to <code>600</code>; sets space between letters to <code>2px</code>; sets top outer spacing to <code>4px</code>. |
| 37 | <code>.auth-layout { display: grid; grid-template-columns: 44% 1fr; min-height: 100dvh; }</code> | Styles the overall sign-in/register layout: uses CSS grid to arrange children; sets the grid column sizes to <code>44% 1fr</code>; sets the minimum height to <code>100dvh</code> (the full dynamic viewport height). |
| 38 | <code>.auth-story { background: var(--navy); color: white; display: flex; flex-direction: column; padding: 48px 60px 35px; position: relative; overflow: hidden; }</code> | Styles the left explanatory story panel: sets the background to <code>var(--navy)</code> using a custom property defined at the document root; sets the foreground/text color to <code>white</code>; uses flexbox to arrange children; stacks flex children vertically; sets inner spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom) to <code>48px 60px 35px</code>; keeps normal flow while creating a positioning reference for descendants; clips content outside the box. |
| 39 | <code>.auth-brand, .story-copy, .story-footer { position: relative; z-index: 1; }</code> | Styles the story brand, text, and footer above the decoration: keeps normal flow while creating a positioning reference for descendants; sets stacking order to <code>1</code>. |
| 40 | <code>.story-copy { max-width: 440px; padding: 60px 0; margin: auto 0; }</code> | Styles the story text block: limits width to <code>440px</code>; sets inner spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom) to <code>60px 0</code>; sets outer spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom; four: top/right/bottom/left) to <code>auto 0</code>. |
| 41 | <code>.story-copy h1 { font-family: Georgia, serif; font-size: 54px; font-weight: 400; letter-spacing: -1.1px; line-height: 1.13; margin: 24px 0; }</code> | Styles the large story heading: sets the ordered font fallback list to <code>Georgia, serif</code>; sets text size to <code>54px</code>; sets font weight to <code>400</code>; sets space between letters to <code>-1.1px</code>; sets line height to <code>1.13</code>; sets outer spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom; four: top/right/bottom/left) to <code>24px 0</code>. |
| 42 | <code>.story-copy &gt; p { max-width: 330px; font-size: 13px; line-height: 1.95; color: #b5c7c0; }</code> | Styles the story description paragraph: limits width to <code>330px</code>; sets text size to <code>13px</code>; sets line height to <code>1.95</code>; sets the foreground/text color to <code>#b5c7c0</code>. |
| 43 | <code>.story-steps { display: grid; gap: 12px; margin-top: 37px; max-width: 350px; }</code> | Styles the three-step checklist: uses CSS grid to arrange children; sets spacing between flex/grid children to <code>12px</code>; sets top outer spacing to <code>37px</code>; limits width to <code>350px</code>. |
| 44 | <code>.story-steps &gt; div { display: flex; gap: 12px; align-items: center; font-size: 12px; color: #d1ded7; }</code> | Styles each checklist row: uses flexbox to arrange children; sets spacing between flex/grid children to <code>12px</code>; centers flex/grid children across the cross axis; sets text size to <code>12px</code>; sets the foreground/text color to <code>#d1ded7</code>. |
| 45 | <code>.story-steps &gt; div &gt; span { display: grid; place-items: center; width: 27px; height: 27px; border-radius: 7px; border: 1px solid #516958; font-size: 9px; color: #97b48a; }</code> | Styles each numbered checklist badge: uses CSS grid to arrange children; centers grid content in both directions; sets width to <code>27px</code>; sets height to <code>27px</code>; rounds corners by <code>7px</code>; sets all four borders to <code>1px solid #516958</code>; sets text size to <code>9px</code>; sets the foreground/text color to <code>#97b48a</code>. |
| 46 | <code>.story-steps svg { color: #a4c18e; margin-left: auto; }</code> | Styles the checklist check icons: sets the foreground/text color to <code>#a4c18e</code>; sets left outer spacing to <code>auto</code> so automatic margins use the available space. |
| 47 | <code>.story-footer { color: #88a398; font-size: 10px; }</code> | Styles the story scope footer: sets the foreground/text color to <code>#88a398</code>; sets text size to <code>10px</code>. |
| 48 | <code>.contour-art { position: absolute; width: 650px; bottom: -60px; left: -70px; opacity: .15; fill: none; stroke: #a9ba77; stroke-width: 1; }</code> | Styles the decorative contour SVG: positions the box outside normal flow relative to its positioned containing block; sets width to <code>650px</code>; sets the positioned bottom offset to <code>-60px</code>; sets the positioned left offset to <code>-70px</code>; sets opacity to <code>.15</code>; leaves SVG shapes unfilled; sets SVG line color to <code>#a9ba77</code>; sets SVG line thickness to <code>1</code>. |
| 49 | <code>.auth-main { padding: 48px 62px 32px; display: flex; flex-direction: column; }</code> | Styles the form-side authentication section: sets inner spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom) to <code>48px 62px 32px</code>; uses flexbox to arrange children; stacks flex children vertically. |
| 50 | <code>.auth-topline { display: flex; align-items: center; gap: 8px; justify-content: flex-end; font-size: 11px; color: #78917d; }</code> | Styles the form-side top caption: uses flexbox to arrange children; centers flex/grid children across the cross axis; sets spacing between flex/grid children to <code>8px</code>; places children at the end of the main axis; sets text size to <code>11px</code>; sets the foreground/text color to <code>#78917d</code>. |
| 51 | <code>.auth-card { width: 100%; max-width: 420px; margin: auto; padding: 45px 0; }</code> | Styles the centered authentication card: sets width to <code>100%</code>; limits width to <code>420px</code>; sets outer spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom; four: top/right/bottom/left) to <code>auto</code>; sets inner spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom) to <code>45px 0</code>. |
| 52 | <code>.auth-card h2 { font-family: Georgia, serif; font-size: 36px; line-height: 1.2; font-weight: 400; letter-spacing: -.5px; margin: 15px 0; }</code> | Styles the authentication card heading: sets the ordered font fallback list to <code>Georgia, serif</code>; sets text size to <code>36px</code>; sets line height to <code>1.2</code>; sets font weight to <code>400</code>; sets space between letters to <code>-.5px</code>; sets outer spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom; four: top/right/bottom/left) to <code>15px 0</code>. |
| 53 | <code>.auth-intro { font-size: 12px; line-height: 1.85; color: var(--muted); margin-bottom: 25px; }</code> | Styles the mode-specific introductory text: sets text size to <code>12px</code>; sets line height to <code>1.85</code>; sets the foreground/text color to <code>var(--muted)</code> using a custom property defined at the document root; sets bottom outer spacing to <code>25px</code>. |
| 54 | <code>.auth-tabs { display: flex; border-bottom: 1px solid #dbe4d6; margin-bottom: 26px; gap: 22px; }</code> | Styles the sign-in/create-account mode selector: uses flexbox to arrange children; sets the bottom border to <code>1px solid #dbe4d6</code>; sets bottom outer spacing to <code>26px</code>; sets spacing between flex/grid children to <code>22px</code>. |
| 55 | <code>.auth-tabs button { background: none; border: 0; border-bottom: 2px solid transparent; color: #7f927c; padding: 12px 0; margin-bottom: -1px; font-size: 12px; font-weight: 600; }</code> | Styles the mode-selector buttons: sets the background to <code>none</code>; sets all four borders to <code>0</code>; sets the bottom border to <code>2px solid transparent</code>; sets the foreground/text color to <code>#7f927c</code>; sets inner spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom) to <code>12px 0</code>; sets bottom outer spacing to <code>-1px</code>; sets text size to <code>12px</code>; sets font weight to <code>600</code>. |
| 56 | <code>.auth-tabs .active { color: var(--teal); border-color: var(--teal); }</code> | Styles the selected mode button: sets the foreground/text color to <code>var(--teal)</code> using a custom property defined at the document root; sets border color to <code>var(--teal)</code> using a custom property defined at the document root. |
| 57 | <code>.auth-form { display: grid; gap: 18px; }</code> | Styles the authentication form: uses CSS grid to arrange children; sets spacing between flex/grid children to <code>18px</code>. |
| 58 | <code>label { display: flex; flex-direction: column; gap: 8px; font-size: 11px; font-weight: 600; color: #476156; }</code> | Styles all field labels: uses flexbox to arrange children; stacks flex children vertically; sets spacing between flex/grid children to <code>8px</code>; sets text size to <code>11px</code>; sets font weight to <code>600</code>; sets the foreground/text color to <code>#476156</code>. |
| 59 | <code>input { width: 100%; background: white; color: #294739; border: 1px solid #d8e2d5; border-radius: 7px; padding: 13px 14px; font-size: 12px; font-weight: 400; min-height: 45px; }</code> | Styles all input fields: sets width to <code>100%</code>; sets the background to <code>white</code>; sets the foreground/text color to <code>#294739</code>; sets all four borders to <code>1px solid #d8e2d5</code>; rounds corners by <code>7px</code>; sets inner spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom) to <code>13px 14px</code>; sets text size to <code>12px</code>; sets font weight to <code>400</code>; sets the minimum height to <code>45px</code>. |
| 60 | <code>input::placeholder { color: #90a089; }</code> | Styles input placeholder text: sets the foreground/text color to <code>#90a089</code>. |
| 61 | <code>.auth-submit { margin-top: 3px; justify-content: space-between; padding-inline: 16px; }</code> | Styles the form submission button: sets top outer spacing to <code>3px</code>; places free space between children along the main axis; sets inner spacing along the inline direction to <code>16px</code>. |
| 62 | <code>.auth-help { font-size: 10px; color: #71866c; line-height: 1.8; margin-top: 22px; overflow-wrap: anywhere; }</code> | Styles the local setup guidance under the form: sets text size to <code>10px</code>; sets the foreground/text color to <code>#71866c</code>; sets line height to <code>1.8</code>; sets top outer spacing to <code>22px</code>; allows long unbroken text to wrap so it does not force overflow. |
| 63 | <code>.notice, .error-box { border-radius: 7px; padding: 12px 14px; font-size: 11px; line-height: 1.7; }</code> | Styles both notice and error messages: rounds corners by <code>7px</code>; sets inner spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom) to <code>12px 14px</code>; sets text size to <code>11px</code>; sets line height to <code>1.7</code>. |
| 64 | <code>.notice { border: 1px solid #d3e6c5; background: #edf5e7; color: #57724b; margin-bottom: 17px; }</code> | Styles nonurgent status notices: sets all four borders to <code>1px solid #d3e6c5</code>; sets the background to <code>#edf5e7</code>; sets the foreground/text color to <code>#57724b</code>; sets bottom outer spacing to <code>17px</code>. |
| 65 | <code>.error-box { border: 1px solid #eed3c8; background: #fdf1eb; color: #a2573d; }</code> | Styles failure alerts: sets all four borders to <code>1px solid #eed3c8</code>; sets the background to <code>#fdf1eb</code>; sets the foreground/text color to <code>#a2573d</code>. |
| 66 | <code>.prototype-note { display: flex; align-items: center; justify-content: center; gap: 10px; color: #8a9a82; font-size: 9px; }</code> | Styles the scope note below the authentication card: uses flexbox to arrange children; centers flex/grid children across the cross axis; centers children along the main axis; sets spacing between flex/grid children to <code>10px</code>; sets the foreground/text color to <code>#8a9a82</code>; sets text size to <code>9px</code>. |
| 67 | <code>.outline-tag { border: 1px solid #d8e1cf; border-radius: 4px; color: #829777; font-size: 8px; letter-spacing: .8px; font-weight: 600; padding: 5px 7px; white-space: nowrap; }</code> | Styles small bordered status/scope tags: sets all four borders to <code>1px solid #d8e1cf</code>; rounds corners by <code>4px</code>; sets the foreground/text color to <code>#829777</code>; sets text size to <code>8px</code>; sets space between letters to <code>.8px</code>; sets font weight to <code>600</code>; sets inner spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom) to <code>5px 7px</code>; keeps text on one line. |
| 68 | <code>.spin { animation: spin 1.1s linear infinite; }</code> | Styles icons marked to rotate while loading: repeats the spin animation every 1.1 seconds at constant speed. |
| 69 | <code>@keyframes spin { to { transform: rotate(360deg); } }</code> | Defines the spin animation. Its final keyframe rotates the element by 360 degrees; with the .spin rule, the turn repeats continuously. |
| 70 | <code>.startup-state { min-height: 100dvh; display: flex; align-items: center; justify-content: center; flex-direction: column; gap: 20px; padding: 30px; text-align: center; }</code> | Styles the session startup/loading/reconnect screen: sets the minimum height to <code>100dvh</code> (the full dynamic viewport height); uses flexbox to arrange children; centers flex/grid children across the cross axis; centers children along the main axis; stacks flex children vertically; sets spacing between flex/grid children to <code>20px</code>; sets inner spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom) to <code>30px</code>; aligns inline text to <code>center</code>. |
| 71 | <code>.startup-state h1 { font-size: 27px; }</code> | Styles the reconnect heading: sets text size to <code>27px</code>. |
| 72 | <code>.startup-state p { max-width: 500px; }</code> | Styles startup explanatory/error paragraphs: limits width to <code>500px</code>. |
| 73 | <code>.skip-link { position: absolute; top: -70px; left: 12px; padding: 11px 17px; border-radius: 5px; z-index: 10; background: white; }</code> | Styles the skip-to-content accessibility link: positions the box outside normal flow relative to its positioned containing block; sets the positioned top offset to <code>-70px</code>; sets the positioned left offset to <code>12px</code>; sets inner spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom) to <code>11px 17px</code>; rounds corners by <code>5px</code>; sets stacking order to <code>10</code>; sets the background to <code>white</code>. |
| 74 | <code>.skip-link:focus { top: 12px; }</code> | Styles the skip link while it has focus: sets the positioned top offset to <code>12px</code>. |
| 75 | <code>.app-shell { min-height: 100dvh; display: flex; }</code> | Styles the signed-in application shell: sets the minimum height to <code>100dvh</code> (the full dynamic viewport height); uses flexbox to arrange children. |
| 76 | <code>.sidebar { width: 247px; position: fixed; inset: 0 auto 0 0; display: flex; flex-direction: column; padding: 33px 24px 0; background: var(--navy); color: white; }</code> | Styles the signed-in navigation sidebar: sets width to <code>247px</code>; fixes the box to the viewport so it stays in place while the page scrolls; sets top/right/bottom/left positioning offsets to <code>0 auto 0 0</code>; uses flexbox to arrange children; stacks flex children vertically; sets inner spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom) to <code>33px 24px 0</code>; sets the background to <code>var(--navy)</code> using a custom property defined at the document root; sets the foreground/text color to <code>white</code>. |
| 77 | <code>.workspace-pill { display: flex; align-items: center; gap: 7px; margin-top: 28px; padding: 9px 11px; border-radius: 6px; border: 1px solid #415b54; color: #b8cbb2; font-size: 10px; }</code> | Styles the sidebar role badge: uses flexbox to arrange children; centers flex/grid children across the cross axis; sets spacing between flex/grid children to <code>7px</code>; sets top outer spacing to <code>28px</code>; sets inner spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom) to <code>9px 11px</code>; rounds corners by <code>6px</code>; sets all four borders to <code>1px solid #415b54</code>; sets the foreground/text color to <code>#b8cbb2</code>; sets text size to <code>10px</code>. |
| 78 | <code>.navigation-label { color: #839e8e; font-size: 8px; letter-spacing: 1.4px; font-weight: 600; margin: 35px 10px 13px; }</code> | Styles the sidebar navigation-group label: sets the foreground/text color to <code>#839e8e</code>; sets text size to <code>8px</code>; sets space between letters to <code>1.4px</code>; sets font weight to <code>600</code>; sets outer spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom; four: top/right/bottom/left) to <code>35px 10px 13px</code>. |
| 79 | <code>.sidebar nav { display: flex; flex-direction: column; gap: 5px; }</code> | Styles the sidebar navigation button group: uses flexbox to arrange children; stacks flex children vertically; sets spacing between flex/grid children to <code>5px</code>. |
| 80 | <code>.nav-link { border: 1px solid transparent; border-radius: 7px; background: none; color: #b7cbc0; display: flex; align-items: center; gap: 10px; padding: 13px 12px; text-align: left; font-size: 12px; }</code> | Styles each navigation button: sets all four borders to <code>1px solid transparent</code>; rounds corners by <code>7px</code>; sets the background to <code>none</code>; sets the foreground/text color to <code>#b7cbc0</code>; uses flexbox to arrange children; centers flex/grid children across the cross axis; sets spacing between flex/grid children to <code>10px</code>; sets inner spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom) to <code>13px 12px</code>; aligns inline text to <code>left</code>; sets text size to <code>12px</code>. |
| 81 | <code>.nav-link:hover { background: #28484a; }</code> | Styles navigation buttons under the pointer: sets the background to <code>#28484a</code>. |
| 82 | <code>.nav-link.active { background: #2e5551; border-color: #416558; color: #d7e8cd; }</code> | Styles the selected navigation button: sets the background to <code>#2e5551</code>; sets border color to <code>#416558</code>; sets the foreground/text color to <code>#d7e8cd</code>. |
| 83 | <code>.sidebar-bottom { margin-top: auto; padding-top: 40px; }</code> | Styles the scope-card/profile area: sets top outer spacing to <code>auto</code> so automatic margins use the available space; sets top inner spacing to <code>40px</code>. |
| 84 | <code>.foundation-card { padding: 21px 17px; border: 1px solid #425d52; background: #284b46; border-radius: 9px; }</code> | Styles the Week 1 scope card: sets inner spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom) to <code>21px 17px</code>; sets all four borders to <code>1px solid #425d52</code>; sets the background to <code>#284b46</code>; rounds corners by <code>9px</code>. |
| 85 | <code>.foundation-card .eyebrow { font-size: 8px; letter-spacing: 1.25px; }</code> | Styles the scope-card eyebrow label: sets text size to <code>8px</code>; sets space between letters to <code>1.25px</code>. |
| 86 | <code>.foundation-card p { margin: 12px 0; font-family: Georgia, serif; font-size: 24px; line-height: 1.35; color: #e4e9da; }</code> | Styles the scope-card headline: sets outer spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom; four: top/right/bottom/left) to <code>12px 0</code>; sets the ordered font fallback list to <code>Georgia, serif</code>; sets text size to <code>24px</code>; sets line height to <code>1.35</code>; sets the foreground/text color to <code>#e4e9da</code>. |
| 87 | <code>.foundation-card &gt; span:last-child { font-size: 9px; color: #97b299; }</code> | Styles the local-demonstration caption: sets text size to <code>9px</code>; sets the foreground/text color to <code>#97b299</code>. |
| 88 | <code>.profile-block { display: flex; align-items: center; gap: 10px; border-top: 1px solid #38564e; margin-top: 23px; padding: 22px 0; }</code> | Styles the signed-in user profile row: uses flexbox to arrange children; centers flex/grid children across the cross axis; sets spacing between flex/grid children to <code>10px</code>; sets the top border to <code>1px solid #38564e</code>; sets top outer spacing to <code>23px</code>; sets inner spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom) to <code>22px 0</code>. |
| 89 | <code>.avatar { width: 34px; height: 34px; display: grid; place-items: center; border-radius: 50%; background: #41654f; color: #d3e4bc; flex: none; font-size: 10px; }</code> | Styles the circular initials badge: sets width to <code>34px</code>; sets height to <code>34px</code>; uses CSS grid to arrange children; centers grid content in both directions; rounds corners by <code>50%</code>; sets the background to <code>#41654f</code>; sets the foreground/text color to <code>#d3e4bc</code>; prevents the item growing or shrinking in flex layout; sets text size to <code>10px</code>. |
| 90 | <code>.profile-name { min-width: 0; }</code> | Styles the user-name/role wrapper: sets the minimum width to <code>0</code>. |
| 91 | <code>.profile-name strong { display: block; font-size: 11px; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 108px; }</code> | Styles the full-name text: displays the item as a block; sets text size to <code>11px</code>; sets font weight to <code>500</code>; clips content outside the box; shows an ellipsis for clipped single-line text when overflow is hidden; keeps text on one line; limits width to <code>108px</code>. |
| 92 | <code>.profile-name small { display: block; font-size: 8px; color: #95af9d; margin-top: 5px; }</code> | Styles the user-role sublabel: displays the item as a block; sets text size to <code>8px</code>; sets the foreground/text color to <code>#95af9d</code>; sets top outer spacing to <code>5px</code>. |
| 93 | <code>.logout-button { margin-left: auto; display: grid; place-items: center; width: 30px; height: 36px; color: #b3c8b2; background: none; border: 0; border-radius: 6px; padding: 0; flex: none; }</code> | Styles the sign-out icon button: sets left outer spacing to <code>auto</code> so automatic margins use the available space; uses CSS grid to arrange children; centers grid content in both directions; sets width to <code>30px</code>; sets height to <code>36px</code>; sets the foreground/text color to <code>#b3c8b2</code>; sets the background to <code>none</code>; sets all four borders to <code>0</code>; rounds corners by <code>6px</code>; sets inner spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom) to <code>0</code>; prevents the item growing or shrinking in flex layout. |
| 94 | <code>.logout-button:hover { background: #385b51; }</code> | Styles the sign-out button under the pointer: sets the background to <code>#385b51</code>. |
| 95 | <code>.workspace { margin-left: 247px; width: calc(100% - 247px); display: flex; flex-direction: column; }</code> | Styles the main area beside the sidebar: sets left outer spacing to <code>247px</code>; sets width to <code>calc(100% - 247px)</code>; uses flexbox to arrange children; stacks flex children vertically. |
| 96 | <code>.workspace-header { padding: 0 39px; min-height: 76px; display: flex; align-items: center; justify-content: space-between; gap: 20px; border-bottom: 1px solid #e2e7dc; background: #fbfcf8; color: #748a6c; font-size: 11px; }</code> | Styles the workspace breadcrumb header: sets inner spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom) to <code>0 39px</code>; sets the minimum height to <code>76px</code>; uses flexbox to arrange children; centers flex/grid children across the cross axis; places free space between children along the main axis; sets spacing between flex/grid children to <code>20px</code>; sets the bottom border to <code>1px solid #e2e7dc</code>; sets the background to <code>#fbfcf8</code>; sets the foreground/text color to <code>#748a6c</code>; sets text size to <code>11px</code>. |
| 97 | <code>.breadcrumb-divider { margin-inline: 15px; color: #afbca5; }</code> | Styles the breadcrumb slash: sets inline-direction outer spacing to <code>15px</code>; sets the foreground/text color to <code>#afbca5</code>. |
| 98 | <code>.week-tag { display: inline-block; background: #eef3e7; color: #80966f; border: 1px solid #dfe7d5; padding: 5px 8px; border-radius: 4px; font-size: 8px; letter-spacing: 1px; white-space: nowrap; }</code> | Styles the WEEK 1 header tag: uses inline-block so the item stays inline but accepts box dimensions; sets the background to <code>#eef3e7</code>; sets the foreground/text color to <code>#80966f</code>; sets all four borders to <code>1px solid #dfe7d5</code>; sets inner spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom) to <code>5px 8px</code>; rounds corners by <code>4px</code>; sets text size to <code>8px</code>; sets space between letters to <code>1px</code>; keeps text on one line. |
| 99 | <code>.workspace-main { padding: 37px 39px 45px; flex: 1; width: 100%; max-width: 1240px; margin-inline: auto; }</code> | Styles the page content inside main: sets inner spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom) to <code>37px 39px 45px</code>; lets the item grow to use available flex space; sets width to <code>100%</code>; limits width to <code>1240px</code>; sets inline-direction outer spacing to <code>auto</code> so automatic margins use the available space. |
| 100 | <code>.page-heading { display: flex; align-items: center; justify-content: space-between; gap: 20px; margin-bottom: 27px; }</code> | Styles the title/description/retry-button row: uses flexbox to arrange children; centers flex/grid children across the cross axis; places free space between children along the main axis; sets spacing between flex/grid children to <code>20px</code>; sets bottom outer spacing to <code>27px</code>. |
| 101 | <code>.page-heading h1 { margin: 12px 0 10px; }</code> | Styles the page heading: sets outer spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom; four: top/right/bottom/left) to <code>12px 0 10px</code>. |
| 102 | <code>.page-heading p { font-size: 12px; color: #7b8e73; line-height: 1.8; }</code> | Styles the page introduction: sets text size to <code>12px</code>; sets the foreground/text color to <code>#7b8e73</code>; sets line height to <code>1.8</code>. |
| 103 | <code>.page-heading &gt; .button { flex: none; }</code> | Styles the retry button directly in the heading row: prevents the item growing or shrinking in flex layout. |
| 104 | <code>.workspace-hero { display: flex; gap: 24px; align-items: flex-start; border: 1px solid #d5e2ce; background: #eaf2e3; border-radius: 12px; padding: 30px; margin-bottom: 26px; }</code> | Styles the signed-in-role permission summary: uses flexbox to arrange children; sets spacing between flex/grid children to <code>24px</code>; aligns children at the start of the cross axis; sets all four borders to <code>1px solid #d5e2ce</code>; sets the background to <code>#eaf2e3</code>; rounds corners by <code>12px</code>; sets inner spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom) to <code>30px</code>; sets bottom outer spacing to <code>26px</code>. |
| 105 | <code>.hero-icon { display: grid; place-items: center; border-radius: 14px; width: 64px; height: 64px; color: #648b58; background: #dae8ce; flex: none; }</code> | Styles the summary shield-icon box: uses CSS grid to arrange children; centers grid content in both directions; rounds corners by <code>14px</code>; sets width to <code>64px</code>; sets height to <code>64px</code>; sets the foreground/text color to <code>#648b58</code>; sets the background to <code>#dae8ce</code>; prevents the item growing or shrinking in flex layout. |
| 106 | <code>.workspace-hero h2 { font-family: Georgia, serif; font-size: 31px; font-weight: 400; letter-spacing: -.4px; margin-top: 12px; line-height: 1.3; }</code> | Styles the permission-summary heading: sets the ordered font fallback list to <code>Georgia, serif</code>; sets text size to <code>31px</code>; sets font weight to <code>400</code>; sets space between letters to <code>-.4px</code>; sets top outer spacing to <code>12px</code>; sets line height to <code>1.3</code>. |
| 107 | <code>.workspace-hero p { font-size: 12px; line-height: 1.9; color: #6e8360; margin-top: 12px; max-width: 620px; }</code> | Styles the summary detail text: sets text size to <code>12px</code>; sets line height to <code>1.9</code>; sets the foreground/text color to <code>#6e8360</code>; sets top outer spacing to <code>12px</code>; limits width to <code>620px</code>. |
| 108 | <code>.access-badge { display: inline-flex; gap: 7px; align-items: center; font-size: 10px; margin-top: 18px; color: #527747; }</code> | Styles the successful session-acceptance badge: uses an inline flex container for aligned text/icons; sets spacing between flex/grid children to <code>7px</code>; centers flex/grid children across the cross axis; sets text size to <code>10px</code>; sets top outer spacing to <code>18px</code>; sets the foreground/text color to <code>#527747</code>. |
| 109 | <code>.panel { background: white; border: 1px solid #dfe7d9; border-radius: 11px; overflow: hidden; }</code> | Styles the white content panels: sets the background to <code>white</code>; sets all four borders to <code>1px solid #dfe7d9</code>; rounds corners by <code>11px</code>; clips content outside the box. |
| 110 | <code>.panel-heading { display: flex; gap: 18px; align-items: center; justify-content: space-between; padding: 25px 26px; border-bottom: 1px solid #e8ece3; }</code> | Styles the panel heading row: uses flexbox to arrange children; sets spacing between flex/grid children to <code>18px</code>; centers flex/grid children across the cross axis; places free space between children along the main axis; sets inner spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom) to <code>25px 26px</code>; sets the bottom border to <code>1px solid #e8ece3</code>. |
| 111 | <code>.panel-heading h2 { font-size: 16px; }</code> | Styles panel titles: sets text size to <code>16px</code>. |
| 112 | <code>.panel-heading p { font-size: 11px; color: #809078; line-height: 1.7; margin-top: 7px; }</code> | Styles panel introduction paragraphs: sets text size to <code>11px</code>; sets the foreground/text color to <code>#809078</code>; sets line height to <code>1.7</code>; sets top outer spacing to <code>7px</code>. |
| 113 | <code>.table-wrap { overflow-x: auto; }</code> | Styles the permissions table overflow wrapper: allows horizontal scrolling when content is wider than the wrapper. |
| 114 | <code>.permissions-table { border-collapse: collapse; width: 100%; text-align: left; font-size: 12px; }</code> | Styles the permissions table: merges adjacent table-cell borders; sets width to <code>100%</code>; aligns inline text to <code>left</code>; sets text size to <code>12px</code>. |
| 115 | <code>.permissions-table th, .permissions-table td { padding: 19px 26px; border-bottom: 1px solid #e9eee3; }</code> | Styles table header/data cells: sets inner spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom) to <code>19px 26px</code>; sets the bottom border to <code>1px solid #e9eee3</code>. |
| 116 | <code>.permissions-table thead th { background: #f8faf4; color: #839475; font-size: 9px; letter-spacing: .6px; font-weight: 600; text-transform: uppercase; }</code> | Styles the permissions table column headers: sets the background to <code>#f8faf4</code>; sets the foreground/text color to <code>#839475</code>; sets text size to <code>9px</code>; sets space between letters to <code>.6px</code>; sets font weight to <code>600</code>; renders the text in uppercase without changing its source value. |
| 117 | <code>.permissions-table tbody th { font-weight: 500; }</code> | Styles workspace row headers: sets font weight to <code>500</code>. |
| 118 | <code>.permissions-table tbody td:last-child { font-size: 11px; color: #728468; white-space: nowrap; }</code> | Styles the server-response cells: sets text size to <code>11px</code>; sets the foreground/text color to <code>#728468</code>; keeps text on one line. |
| 119 | <code>.permission-state { display: inline-flex; align-items: center; gap: 7px; border: 1px solid #e0e5d9; border-radius: 5px; padding: 6px 9px; color: #87927d; font-size: 10px; white-space: nowrap; }</code> | Styles access-result badges: uses an inline flex container for aligned text/icons; centers flex/grid children across the cross axis; sets spacing between flex/grid children to <code>7px</code>; sets all four borders to <code>1px solid #e0e5d9</code>; rounds corners by <code>5px</code>; sets inner spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom) to <code>6px 9px</code>; sets the foreground/text color to <code>#87927d</code>; sets text size to <code>10px</code>; keeps text on one line. |
| 120 | <code>.permission-state.allowed { color: #48713c; background: #eff6e9; border-color: #d6e5cd; }</code> | Styles allowed-access badges: sets the foreground/text color to <code>#48713c</code>; sets the background to <code>#eff6e9</code>; sets border color to <code>#d6e5cd</code>. |
| 121 | <code>.permission-state.denied { color: #876c48; background: #faf4e9; border-color: #e8dbc8; }</code> | Styles server-denied badges: sets the foreground/text color to <code>#876c48</code>; sets the background to <code>#faf4e9</code>; sets border color to <code>#e8dbc8</code>. |
| 122 | <code>.panel-note { font-size: 11px; color: #819178; line-height: 1.8; padding: 20px 26px; background: #fbfcf8; }</code> | Styles the explanatory footnotes in panels: sets text size to <code>11px</code>; sets the foreground/text color to <code>#819178</code>; sets line height to <code>1.8</code>; sets inner spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom) to <code>20px 26px</code>; sets the background to <code>#fbfcf8</code>. |
| 123 | <code>.panel-error { margin: 20px 26px 0; }</code> | Styles the failed-check alert in a panel: sets outer spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom; four: top/right/bottom/left) to <code>20px 26px 0</code>. |
| 124 | <code>.account-facts { display: grid; grid-template-columns: 1fr 1fr; gap: 28px; margin: 0; padding: 28px 26px; }</code> | Styles the account description list: uses CSS grid to arrange children; sets the grid column sizes to <code>1fr 1fr</code>; sets spacing between flex/grid children to <code>28px</code>; sets outer spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom; four: top/right/bottom/left) to <code>0</code>; sets inner spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom) to <code>28px 26px</code>. |
| 125 | <code>.account-facts &gt; div { min-width: 0; }</code> | Styles each account fact wrapper: sets the minimum width to <code>0</code>. |
| 126 | <code>.account-facts dt { color: #809078; font-size: 10px; margin-bottom: 9px; }</code> | Styles account fact labels: sets the foreground/text color to <code>#809078</code>; sets text size to <code>10px</code>; sets bottom outer spacing to <code>9px</code>. |
| 127 | <code>.account-facts dd { margin: 0; font-size: 13px; color: #385443; overflow-wrap: anywhere; line-height: 1.7; }</code> | Styles account fact values: sets outer spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom; four: top/right/bottom/left) to <code>0</code>; sets text size to <code>13px</code>; sets the foreground/text color to <code>#385443</code>; allows long unbroken text to wrap so it does not force overflow; sets line height to <code>1.7</code>. |
| 128 | <code>.account-panel .panel-heading &gt; svg { color: #7c956b; }</code> | Styles the account-panel user icon: sets the foreground/text color to <code>#7c956b</code>. |
| 129 | <code>.workspace-footer { display: flex; justify-content: space-between; gap: 20px; padding: 18px 39px; border-top: 1px solid #e1e7d8; color: #899a7e; font-size: 9px; line-height: 1.6; }</code> | Styles the main-area project footer: uses flexbox to arrange children; places free space between children along the main axis; sets spacing between flex/grid children to <code>20px</code>; sets inner spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom) to <code>18px 39px</code>; sets the top border to <code>1px solid #e1e7d8</code>; sets the foreground/text color to <code>#899a7e</code>; sets text size to <code>9px</code>; sets line height to <code>1.6</code>. |
| 130 | <code>@media (min-width: 1600px) {</code> | Begins responsive overrides for viewport widths of at least 1600px; these rules take effect only when the condition matches. |
| 131 | <code>.auth-story { padding-inline: 80px; }</code> | Styles the left explanatory story panel within the current (min-width: 1600px) media condition: sets inner spacing along the inline direction to <code>80px</code>. |
| 132 | <code>.auth-main { padding-inline: 90px; }</code> | Styles the form-side authentication section within the current (min-width: 1600px) media condition: sets inner spacing along the inline direction to <code>90px</code>. |
| 133 | <code>.story-copy h1 { font-size: 62px; }</code> | Styles the large story heading within the current (min-width: 1600px) media condition: sets text size to <code>62px</code>. |
| 134 | <code>}</code> | Closes the responsive/media block for (min-width: 1600px). |
| 135 | <code>@media (max-width: 1100px) {</code> | Begins responsive overrides for viewport widths at or below 1100px. When several max-width conditions match, later rules can override earlier rules. |
| 136 | <code>.auth-story { padding-inline: 35px; }</code> | Styles the left explanatory story panel within the current (max-width: 1100px) media condition: sets inner spacing along the inline direction to <code>35px</code>. |
| 137 | <code>.auth-main { padding-inline: 38px; }</code> | Styles the form-side authentication section within the current (max-width: 1100px) media condition: sets inner spacing along the inline direction to <code>38px</code>. |
| 138 | <code>.story-copy h1 { font-size: 43px; }</code> | Styles the large story heading within the current (max-width: 1100px) media condition: sets text size to <code>43px</code>. |
| 139 | <code>.sidebar { width: 222px; padding-inline: 17px; }</code> | Styles the signed-in navigation sidebar within the current (max-width: 1100px) media condition: sets width to <code>222px</code>; sets inner spacing along the inline direction to <code>17px</code>. |
| 140 | <code>.workspace { width: calc(100% - 222px); margin-left: 222px; }</code> | Styles the main area beside the sidebar within the current (max-width: 1100px) media condition: sets width to <code>calc(100% - 222px)</code>; sets left outer spacing to <code>222px</code>. |
| 141 | <code>.workspace-main { padding: 30px 25px; }</code> | Styles the page content inside main within the current (max-width: 1100px) media condition: sets inner spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom) to <code>30px 25px</code>. |
| 142 | <code>.workspace-header, .workspace-footer { padding-inline: 25px; }</code> | Styles both the header and footer within the current (max-width: 1100px) media condition: sets inner spacing along the inline direction to <code>25px</code>. |
| 143 | <code>.page-heading { flex-wrap: wrap; gap: 13px; }</code> | Styles the title/description/retry-button row within the current (max-width: 1100px) media condition: allows flex children to wrap onto additional lines; sets spacing between flex/grid children to <code>13px</code>. |
| 144 | <code>}</code> | Closes the responsive/media block for (max-width: 1100px). |
| 145 | <code>@media (max-width: 760px) {</code> | Begins responsive overrides for viewport widths at or below 760px. When several max-width conditions match, later rules can override earlier rules. |
| 146 | <code>.auth-layout { grid-template-columns: 40% 1fr; }</code> | Styles the overall sign-in/register layout within the current (max-width: 760px) media condition: sets the grid column sizes to <code>40% 1fr</code>. |
| 147 | <code>.auth-story { padding: 32px 24px; }</code> | Styles the left explanatory story panel within the current (max-width: 760px) media condition: sets inner spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom) to <code>32px 24px</code>. |
| 148 | <code>.auth-main { padding: 32px 25px; }</code> | Styles the form-side authentication section within the current (max-width: 760px) media condition: sets inner spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom) to <code>32px 25px</code>. |
| 149 | <code>.story-copy h1 { font-size: 35px; }</code> | Styles the large story heading within the current (max-width: 760px) media condition: sets text size to <code>35px</code>. |
| 150 | <code>.auth-card h2 { font-size: 31px; }</code> | Styles the authentication card heading within the current (max-width: 760px) media condition: sets text size to <code>31px</code>. |
| 151 | <code>.auth-topline { font-size: 9px; }</code> | Styles the form-side top caption within the current (max-width: 760px) media condition: sets text size to <code>9px</code>. |
| 152 | <code>.story-steps &gt; div { font-size: 10px; }</code> | Styles each checklist row within the current (max-width: 760px) media condition: sets text size to <code>10px</code>. |
| 153 | <code>.sidebar { width: 190px; padding: 28px 12px 0; }</code> | Styles the signed-in navigation sidebar within the current (max-width: 760px) media condition: sets width to <code>190px</code>; sets inner spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom) to <code>28px 12px 0</code>. |
| 154 | <code>.sidebar .brand { gap: 8px; }</code> | Styles the sidebar brand link within the current (max-width: 760px) media condition: sets spacing between flex/grid children to <code>8px</code>. |
| 155 | <code>.sidebar .brand &gt; span:last-child { font-size: 18px; }</code> | Styles the sidebar brand text within the current (max-width: 760px) media condition: sets text size to <code>18px</code>. |
| 156 | <code>.sidebar .brand small { font-size: 6px; letter-spacing: 1.6px; }</code> | Styles the sidebar brand sublabel within the current (max-width: 760px) media condition: sets text size to <code>6px</code>; sets space between letters to <code>1.6px</code>. |
| 157 | <code>.sidebar .brand-symbol { width: 35px; height: 38px; border-radius: 9px; }</code> | Styles the sidebar brand icon box within the current (max-width: 760px) media condition: sets width to <code>35px</code>; sets height to <code>38px</code>; rounds corners by <code>9px</code>. |
| 158 | <code>.workspace { width: calc(100% - 190px); margin-left: 190px; }</code> | Styles the main area beside the sidebar within the current (max-width: 760px) media condition: sets width to <code>calc(100% - 190px)</code>; sets left outer spacing to <code>190px</code>. |
| 159 | <code>.workspace-main { padding: 27px 20px; }</code> | Styles the page content inside main within the current (max-width: 760px) media condition: sets inner spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom) to <code>27px 20px</code>. |
| 160 | <code>.workspace-header, .workspace-footer { padding-inline: 20px; }</code> | Styles both the header and footer within the current (max-width: 760px) media condition: sets inner spacing along the inline direction to <code>20px</code>. |
| 161 | <code>.workspace-header { min-height: 66px; }</code> | Styles the workspace breadcrumb header within the current (max-width: 760px) media condition: sets the minimum height to <code>66px</code>. |
| 162 | <code>.foundation-card { padding: 15px 12px; }</code> | Styles the Week 1 scope card within the current (max-width: 760px) media condition: sets inner spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom) to <code>15px 12px</code>. |
| 163 | <code>.foundation-card p { font-size: 20px; }</code> | Styles the scope-card headline within the current (max-width: 760px) media condition: sets text size to <code>20px</code>. |
| 164 | <code>.profile-block { gap: 7px; }</code> | Styles the signed-in user profile row within the current (max-width: 760px) media condition: sets spacing between flex/grid children to <code>7px</code>. |
| 165 | <code>.profile-name strong { max-width: 85px; font-size: 10px; }</code> | Styles the full-name text within the current (max-width: 760px) media condition: limits width to <code>85px</code>; sets text size to <code>10px</code>. |
| 166 | <code>.avatar { width: 29px; height: 29px; }</code> | Styles the circular initials badge within the current (max-width: 760px) media condition: sets width to <code>29px</code>; sets height to <code>29px</code>. |
| 167 | <code>.nav-link { font-size: 11px; gap: 8px; padding-inline: 9px; }</code> | Styles each navigation button within the current (max-width: 760px) media condition: sets text size to <code>11px</code>; sets spacing between flex/grid children to <code>8px</code>; sets inner spacing along the inline direction to <code>9px</code>. |
| 168 | <code>h1 { font-size: 30px; }</code> | Styles top-level headings within the current (max-width: 760px) media condition: sets text size to <code>30px</code>. |
| 169 | <code>.workspace-hero { padding: 24px; gap: 17px; }</code> | Styles the signed-in-role permission summary within the current (max-width: 760px) media condition: sets inner spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom) to <code>24px</code>; sets spacing between flex/grid children to <code>17px</code>. |
| 170 | <code>.hero-icon { display: none; }</code> | Styles the summary shield-icon box within the current (max-width: 760px) media condition: hides the item from layout and the accessibility tree. |
| 171 | <code>.workspace-hero h2 { font-size: 29px; }</code> | Styles the permission-summary heading within the current (max-width: 760px) media condition: sets text size to <code>29px</code>. |
| 172 | <code>.panel-heading, .panel-note { padding: 20px; }</code> | Styles panel headings and footnotes within the current (max-width: 760px) media condition: sets inner spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom) to <code>20px</code>. |
| 173 | <code>.permissions-table th, .permissions-table td { padding: 16px 18px; }</code> | Styles table header/data cells within the current (max-width: 760px) media condition: sets inner spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom) to <code>16px 18px</code>. |
| 174 | <code>.workspace-footer { flex-direction: column; gap: 5px; }</code> | Styles the main-area project footer within the current (max-width: 760px) media condition: stacks flex children vertically; sets spacing between flex/grid children to <code>5px</code>. |
| 175 | <code>.account-facts { padding: 25px 20px; grid-template-columns: 1fr; gap: 22px; }</code> | Styles the account description list within the current (max-width: 760px) media condition: sets inner spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom) to <code>25px 20px</code>; sets the grid column sizes to <code>1fr</code>; sets spacing between flex/grid children to <code>22px</code>. |
| 176 | <code>}</code> | Closes the responsive/media block for (max-width: 760px). |
| 177 | <code>@media (max-width: 580px) {</code> | Begins responsive overrides for viewport widths at or below 580px. When several max-width conditions match, later rules can override earlier rules. |
| 178 | <code>.auth-layout { display: flex; flex-direction: column; }</code> | Styles the overall sign-in/register layout within the current (max-width: 580px) media condition: uses flexbox to arrange children; stacks flex children vertically. |
| 179 | <code>.auth-story { padding: 25px 27px; }</code> | Styles the left explanatory story panel within the current (max-width: 580px) media condition: sets inner spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom) to <code>25px 27px</code>. |
| 180 | <code>.story-copy { margin: 0; padding: 27px 0 7px; }</code> | Styles the story text block within the current (max-width: 580px) media condition: sets outer spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom; four: top/right/bottom/left) to <code>0</code>; sets inner spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom) to <code>27px 0 7px</code>. |
| 181 | <code>.story-copy .eyebrow, .story-copy &gt; p, .story-steps, .story-footer { display: none; }</code> | Styles the story eyebrow, description, checklist, and footer within the current (max-width: 580px) media condition: hides the item from layout and the accessibility tree. |
| 182 | <code>.story-copy h1 { font-size: 31px; letter-spacing: -.6px; margin: 0; }</code> | Styles the large story heading within the current (max-width: 580px) media condition: sets text size to <code>31px</code>; sets space between letters to <code>-.6px</code>; sets outer spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom; four: top/right/bottom/left) to <code>0</code>. |
| 183 | <code>.story-copy h1 br { display: none; }</code> | Styles the explicit line break inside the story heading within the current (max-width: 580px) media condition: hides the item from layout and the accessibility tree. |
| 184 | <code>.contour-art { width: 450px; bottom: -200px; left: 0; }</code> | Styles the decorative contour SVG within the current (max-width: 580px) media condition: sets width to <code>450px</code>; sets the positioned bottom offset to <code>-200px</code>; sets the positioned left offset to <code>0</code>. |
| 185 | <code>.auth-main { padding: 27px; }</code> | Styles the form-side authentication section within the current (max-width: 580px) media condition: sets inner spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom) to <code>27px</code>. |
| 186 | <code>.auth-topline { display: none; }</code> | Styles the form-side top caption within the current (max-width: 580px) media condition: hides the item from layout and the accessibility tree. |
| 187 | <code>.auth-card { padding: 10px 0 34px; }</code> | Styles the centered authentication card within the current (max-width: 580px) media condition: sets inner spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom) to <code>10px 0 34px</code>. |
| 188 | <code>.auth-card h2 { font-size: 30px; }</code> | Styles the authentication card heading within the current (max-width: 580px) media condition: sets text size to <code>30px</code>. |
| 189 | <code>.prototype-note { align-items: flex-start; justify-content: flex-start; font-size: 9px; line-height: 1.8; }</code> | Styles the scope note below the authentication card within the current (max-width: 580px) media condition: aligns children at the start of the cross axis; places children at the start of the main axis; sets text size to <code>9px</code>; sets line height to <code>1.8</code>. |
| 190 | <code>.app-shell { display: block; }</code> | Styles the signed-in application shell within the current (max-width: 580px) media condition: displays the item as a block. |
| 191 | <code>.sidebar { width: 100%; position: static; padding: 18px 19px 0; flex-direction: row; flex-wrap: wrap; align-items: center; }</code> | Styles the signed-in navigation sidebar within the current (max-width: 580px) media condition: sets width to <code>100%</code>; returns the box to normal document positioning; sets inner spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom) to <code>18px 19px 0</code>; arranges flex children horizontally; allows flex children to wrap onto additional lines; centers flex/grid children across the cross axis. |
| 192 | <code>.sidebar .brand { width: fit-content; }</code> | Styles the sidebar brand link within the current (max-width: 580px) media condition: sets width to <code>fit-content</code>. |
| 193 | <code>.sidebar .brand &gt; span:last-child { font-size: 21px; }</code> | Styles the sidebar brand text within the current (max-width: 580px) media condition: sets text size to <code>21px</code>. |
| 194 | <code>.workspace-pill, .navigation-label, .foundation-card { display: none; }</code> | Styles the sidebar role pill, navigation label, and scope card within the current (max-width: 580px) media condition: hides the item from layout and the accessibility tree. |
| 195 | <code>.sidebar-bottom { margin: 0 0 0 auto; padding: 0; }</code> | Styles the scope-card/profile area within the current (max-width: 580px) media condition: sets outer spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom; four: top/right/bottom/left) to <code>0 0 0 auto</code>; sets inner spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom) to <code>0</code>. |
| 196 | <code>.profile-block { border: 0; margin: 0; padding: 0; gap: 10px; }</code> | Styles the signed-in user profile row within the current (max-width: 580px) media condition: sets all four borders to <code>0</code>; sets outer spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom; four: top/right/bottom/left) to <code>0</code>; sets inner spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom) to <code>0</code>; sets spacing between flex/grid children to <code>10px</code>. |
| 197 | <code>.profile-name { display: none; }</code> | Styles the user-name/role wrapper within the current (max-width: 580px) media condition: hides the item from layout and the accessibility tree. |
| 198 | <code>.avatar { width: 31px; height: 31px; }</code> | Styles the circular initials badge within the current (max-width: 580px) media condition: sets width to <code>31px</code>; sets height to <code>31px</code>. |
| 199 | <code>.sidebar nav { flex-direction: row; width: 100%; margin-top: 18px; border-top: 1px solid #3b565b; gap: 6px; padding: 8px 0; }</code> | Styles the sidebar navigation button group within the current (max-width: 580px) media condition: arranges flex children horizontally; sets width to <code>100%</code>; sets top outer spacing to <code>18px</code>; sets the top border to <code>1px solid #3b565b</code>; sets spacing between flex/grid children to <code>6px</code>; sets inner spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom) to <code>8px 0</code>. |
| 200 | <code>.nav-link { min-height: 42px; padding: 9px; flex: 1; justify-content: center; font-size: 11px; gap: 7px; }</code> | Styles each navigation button within the current (max-width: 580px) media condition: sets the minimum height to <code>42px</code>; sets inner spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom) to <code>9px</code>; lets the item grow to use available flex space; centers children along the main axis; sets text size to <code>11px</code>; sets spacing between flex/grid children to <code>7px</code>. |
| 201 | <code>.nav-link svg { width: 16px; }</code> | Styles navigation icons within the current (max-width: 580px) media condition: sets width to <code>16px</code>. |
| 202 | <code>.workspace { width: 100%; margin: 0; }</code> | Styles the main area beside the sidebar within the current (max-width: 580px) media condition: sets width to <code>100%</code>; sets outer spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom; four: top/right/bottom/left) to <code>0</code>. |
| 203 | <code>.workspace-header { min-height: 55px; font-size: 10px; }</code> | Styles the workspace breadcrumb header within the current (max-width: 580px) media condition: sets the minimum height to <code>55px</code>; sets text size to <code>10px</code>. |
| 204 | <code>.workspace-main { padding: 26px 19px; }</code> | Styles the page content inside main within the current (max-width: 580px) media condition: sets inner spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom) to <code>26px 19px</code>. |
| 205 | <code>.page-heading p { font-size: 11px; }</code> | Styles the page introduction within the current (max-width: 580px) media condition: sets text size to <code>11px</code>. |
| 206 | <code>.page-heading .eyebrow { font-size: 8px; }</code> | Styles the page eyebrow label within the current (max-width: 580px) media condition: sets text size to <code>8px</code>. |
| 207 | <code>.page-heading .button { font-size: 11px; padding: 10px 13px; }</code> | Styles the page retry button within the current (max-width: 580px) media condition: sets text size to <code>11px</code>; sets inner spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom) to <code>10px 13px</code>. |
| 208 | <code>.workspace-hero { padding: 24px 22px; }</code> | Styles the signed-in-role permission summary within the current (max-width: 580px) media condition: sets inner spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom) to <code>24px 22px</code>. |
| 209 | <code>.workspace-hero h2 { font-size: 28px; }</code> | Styles the permission-summary heading within the current (max-width: 580px) media condition: sets text size to <code>28px</code>. |
| 210 | <code>.workspace-hero p { font-size: 11px; }</code> | Styles the summary detail text within the current (max-width: 580px) media condition: sets text size to <code>11px</code>. |
| 211 | <code>.access-badge { font-size: 9px; }</code> | Styles the successful session-acceptance badge within the current (max-width: 580px) media condition: sets text size to <code>9px</code>. |
| 212 | <code>.panel-heading { padding: 20px 17px; }</code> | Styles the panel heading row within the current (max-width: 580px) media condition: sets inner spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom) to <code>20px 17px</code>. |
| 213 | <code>.panel-heading h2 { font-size: 15px; }</code> | Styles panel titles within the current (max-width: 580px) media condition: sets text size to <code>15px</code>. |
| 214 | <code>.panel-heading p { font-size: 10px; }</code> | Styles panel introduction paragraphs within the current (max-width: 580px) media condition: sets text size to <code>10px</code>. |
| 215 | <code>.panel-heading .outline-tag { font-size: 7px; padding-inline: 5px; }</code> | Styles the panel status tag within the current (max-width: 580px) media condition: sets text size to <code>7px</code>; sets inner spacing along the inline direction to <code>5px</code>. |
| 216 | <code>.permissions-table { font-size: 10px; }</code> | Styles the permissions table within the current (max-width: 580px) media condition: sets text size to <code>10px</code>. |
| 217 | <code>.permissions-table th, .permissions-table td { padding: 16px 11px; }</code> | Styles table header/data cells within the current (max-width: 580px) media condition: sets inner spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom) to <code>16px 11px</code>. |
| 218 | <code>.permissions-table thead th { font-size: 8px; letter-spacing: .2px; }</code> | Styles the permissions table column headers within the current (max-width: 580px) media condition: sets text size to <code>8px</code>; sets space between letters to <code>.2px</code>. |
| 219 | <code>.permissions-table tbody td:last-child, .permission-state { font-size: 9px; }</code> | Styles server-response text and permission badges within the current (max-width: 580px) media condition: sets text size to <code>9px</code>. |
| 220 | <code>.permission-state { padding: 5px 6px; gap: 5px; }</code> | Styles access-result badges within the current (max-width: 580px) media condition: sets inner spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom) to <code>5px 6px</code>; sets spacing between flex/grid children to <code>5px</code>. |
| 221 | <code>.panel-note { padding: 18px; font-size: 10px; }</code> | Styles the explanatory footnotes in panels within the current (max-width: 580px) media condition: sets inner spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom) to <code>18px</code>; sets text size to <code>10px</code>. |
| 222 | <code>.panel-error { margin-inline: 18px; }</code> | Styles the failed-check alert in a panel within the current (max-width: 580px) media condition: sets inline-direction outer spacing to <code>18px</code>. |
| 223 | <code>.workspace-footer { padding: 17px 21px; font-size: 8px; }</code> | Styles the main-area project footer within the current (max-width: 580px) media condition: sets inner spacing (one value: all sides; two: vertical/horizontal; three: top/horizontal/bottom) to <code>17px 21px</code>; sets text size to <code>8px</code>. |
| 224 | <code>}</code> | Closes the responsive/media block for (max-width: 580px). |
| 225 | <code>@media (prefers-reduced-motion: reduce) {</code> | Begins overrides when the user has requested reduced motion in system/browser preferences. |
| 226 | <code>*, *::before, *::after { animation-duration: .01ms !important; animation-iteration-count: 1 !important; transition-duration: .01ms !important; scroll-behavior: auto !important; }</code> | Styles all elements and their before/after pseudo-elements within the current (prefers-reduced-motion: reduce) media condition: sets animation duration to <code>.01ms !important</code> with important priority over ordinary declarations; sets the number of animation repetitions to <code>1 !important</code> with important priority over ordinary declarations; sets transition duration to <code>.01ms !important</code> with important priority over ordinary declarations; sets scrolling behavior to <code>auto !important</code> with important priority over ordinary declarations. |
| 227 | <code>}</code> | Closes the responsive/media block for (prefers-reduced-motion: reduce). |

### `frontend/index.html`

**Purpose:** HTML document and React mount container.

The browser first receives this HTML page. Its module script loads main.jsx, and main.jsx renders App inside the root div. Metadata sets document encoding, responsive sizing, browser theme, page description, title, and an inline SVG favicon.

**Coverage:** 15 physical lines; 15 nonblank lines explained; 0 blank lines are readability separators.

| Line | Code | Explanation |
| --- | --- | --- |
| 1 | <code>&lt;!doctype html&gt;</code> | Declares the HTML5 document type, enabling standards-mode HTML rendering. |
| 2 | <code>&lt;html lang="en"&gt;</code> | Opens the document and declares its content language as English for accessibility and browser language handling. |
| 3 | <code>&lt;head&gt;</code> | Opens head, which contains document metadata rather than the visible app interface. |
| 4 | <code>&lt;meta charset="UTF-8" /&gt;</code> | Selects UTF-8 text encoding so punctuation and other Unicode text display correctly. |
| 5 | <code>&lt;meta name="viewport" content="width=device-width, initial-scale=1.0" /&gt;</code> | Sets the viewport to the device width and starts at normal scale, allowing the stylesheet's responsive breakpoints to match mobile screen widths. |
| 6 | <code>&lt;meta name="theme-color" content="#15353d" /&gt;</code> | Supplies the dark theme color that supported browsers may use for browser chrome or UI around the page. |
| 7 | <code>&lt;link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='14' fill='%23237c6b'/%3E%3Ctext x='32' y='46' text-anchor='middle' font-family='sans-serif' font-size='44' fill='white'%3EA%3C/text%3E%3C/svg%3E" /&gt;</code> | Defines the favicon as a URL-encoded inline SVG: a 64-by-64 teal rounded square with a centered white A. It requires no separate favicon image file. |
| 8 | <code>&lt;meta name="description" content="ResQ ResQ Kerala Week 1 authentication and role permissions implementation." /&gt;</code> | Sets the page description used by browsers/search tools; it describes the Week 1 authentication and role-permissions scope. |
| 9 | <code>&lt;title&gt;ResQ · Week 1 · ResQ Kerala&lt;/title&gt;</code> | Sets the document title displayed in the browser tab. |
| 10 | <code>&lt;/head&gt;</code> | Closes the metadata head. |
| 11 | <code>&lt;body&gt;</code> | Opens the visible document body. |
| 12 | <code>&lt;div id="root"&gt;&lt;/div&gt;</code> | Creates the empty root container that ReactDOM.createRoot locates and fills. |
| 13 | <code>&lt;script type="module" src="/src/main.jsx"&gt;&lt;/script&gt;</code> | Loads main.jsx as an ES module. Vite transforms its JSX and resolves its module imports during development/build. |
| 14 | <code>&lt;/body&gt;</code> | Closes the document body. |
| 15 | <code>&lt;/html&gt;</code> | Closes the HTML document. |

### `frontend/vite.config.js`

**Purpose:** Local frontend server, preview, React transformation, and backend proxy.

Vite development and build preview bind to 127.0.0.1:5175. Requests beginning /api or /health are forwarded to 127.0.0.1:8012 without stripping those prefixes. The frontend can therefore call relative API paths. strictPort makes an occupied port an error instead of silently choosing another port. This describes the Vite servers; an arbitrary static production host does not automatically inherit this proxy.

**Coverage:** 13 physical lines; 11 nonblank lines explained; 2 blank lines are readability separators.

| Line | Code | Explanation |
| --- | --- | --- |
| 1 | <code>import { defineConfig } from 'vite';</code> | Imports Vite's defineConfig helper, which wraps the configuration object and supports editor/type tooling. |
| 2 | <code>import react from '@vitejs/plugin-react';</code> | Imports the React plugin used to transform React JSX and provide development integration such as Fast Refresh. |
| 4 | <code>const proxy = {</code> | Starts a reusable proxy configuration object shared by dev and preview. |
| 5 | <code>'/api': { target: 'http://127.0.0.1:8012', changeOrigin: true },</code> | Proxies requests whose path starts with /api to the local backend on port 8012. changeOrigin changes the proxied Host header to match the target; no rewrite option removes /api. |
| 6 | <code>'/health': { target: 'http://127.0.0.1:8012', changeOrigin: true },</code> | Similarly forwards /health requests to that backend, preserving their path. |
| 7 | <code>};</code> | Closes the proxy object. |
| 9 | <code>export default defineConfig({</code> | Exports the Vite configuration through defineConfig. |
| 10 | <code>plugins: [react()],</code> | Installs the React plugin by calling react() and putting its result in the plugin list. |
| 11 | <code>server: { host: '127.0.0.1', port: 5175, strictPort: true, proxy },</code> | Configures the development server on loopback port 5175, requires that exact port, and applies the shared backend proxy. |
| 12 | <code>preview: { host: '127.0.0.1', port: 5175, strictPort: true, proxy },</code> | Configures the built-output preview server with the same loopback host, strict port, and proxy. |
| 13 | <code>});</code> | Closes the configuration object and defineConfig call. |

### `frontend/package.json`

**Purpose:** Frontend package identity, scripts, and dependency versions.

This JSON file tells the package manager what to install and provides the three frontend commands. Runtime dependencies supply React rendering and icons; development dependencies supply Vite and its React integration. The strings pin the declared direct versions; package-lock.json records the resolved dependency graph.

**Coverage:** 20 physical lines; 20 nonblank lines explained; 0 blank lines are readability separators.

| Line | Code | Explanation |
| --- | --- | --- |
| 1 | <code>{</code> | Opens the top-level JSON package object. |
| 2 | <code>"name": "resq-week1",</code> | Names the local npm package resq-week1. |
| 3 | <code>"version": "1.0.0",</code> | Declares the project's package version as 1.0.0. |
| 4 | <code>"private": true,</code> | Marks the package private, preventing accidental publication with the normal npm publishing workflow. |
| 5 | <code>"type": "module",</code> | Declares JavaScript package files as ES modules, matching import/export syntax in vite.config.js. |
| 6 | <code>"scripts": {</code> | Opens the scripts object containing package-manager command aliases. |
| 7 | <code>"dev": "vite",</code> | Defines npm run dev (or the equivalent package-manager script) to launch Vite's development server. |
| 8 | <code>"build": "vite build",</code> | Defines npm run build to produce Vite's production build output, normally in dist. |
| 9 | <code>"preview": "vite preview"</code> | Defines npm run preview to serve an existing production build for local checking; it is not a build command itself. |
| 10 | <code>},</code> | Closes scripts. |
| 11 | <code>"dependencies": {</code> | Opens the runtime dependency object. |
| 12 | <code>"lucide-react": "1.52.0",</code> | Pins lucide-react to 1.52.0, supplying the SVG icon components imported by App and Login. |
| 13 | <code>"react": "19.3.0",</code> | Pins react to 19.3.0, supplying components, hooks, and the React rendering model. |
| 14 | <code>"react-dom": "19.3.0"</code> | Pins react-dom to 19.3.0, supplying the browser renderer used in main.jsx. |
| 15 | <code>},</code> | Closes runtime dependencies. |
| 16 | <code>"devDependencies": {</code> | Opens development dependencies used by frontend tooling. |
| 17 | <code>"@vitejs/plugin-react": "6.1.2",</code> | Pins @vitejs/plugin-react to 6.1.2, supplying React integration for Vite. |
| 18 | <code>"vite": "8.3.3"</code> | Pins vite to 8.3.3, supplying the development server, build pipeline, and preview server. |
| 19 | <code>}</code> | Closes development dependencies. |
| 20 | <code>}</code> | Closes the complete JSON object. JSON keys/string values use double quotes, unlike optional single-quoted strings in JavaScript source. |

## Supporting scripts and configuration

This section explains the runnable project support files using their physical source line numbers. Every nonblank source line has a row. Blank lines only separate code visually and have no runtime effect. Code is reproduced from the files as inspected; no setup, start, stop, or credential-reading scripts were executed.

### `scripts/common.ps1`

Shared PowerShell helpers loaded by start.ps1 and stop.ps1. Dot-sourcing places its variables and functions into the caller's scope, so both scripts use the same project paths, stored Python executable, process-ownership checks, and readiness polling.

| Line | Code | Explanation |
| --- | --- | --- |
| 1 | `$ErrorActionPreference = 'Stop'` | Treat PowerShell errors as stopping errors, so an unexpected failure normally interrupts the calling script instead of continuing silently. |
| 2 | `$ProjectRoot = Split-Path -Parent $PSScriptRoot` | Take the parent of the scripts directory to locate the standalone project root. $PSScriptRoot is the directory containing this script. |
| 3 | `$RuntimePath = Join-Path $ProjectRoot '.runtime'` | Build the path to the local .runtime directory, where setup metadata, process records, and logs are kept. |
| 4 | `$setupPath = Join-Path $RuntimePath 'setup.json'` | Build the path to setup.json, which records the Python executable chosen during setup. |
| 5 | `if (-not (Test-Path -LiteralPath $setupPath)) { throw 'Run .\scripts\setup.ps1 first.' }` | Stop with a clear instruction if setup.json does not exist; start and stop therefore depend on setup having completed. |
| 6 | `$Setup = Get-Content -LiteralPath $setupPath -Raw \| ConvertFrom-Json` | Read setup.json as one string and parse its JSON into a PowerShell object. Later code accesses the stored executable as $Setup.python. |
| 7 | `function Test-WorkspaceProcess([int]$ProcessId, [string]$Name) {` | Define a helper that accepts an integer process ID and service name and answers whether that process looks like this project's service. |
| 8 | `$info = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue` | Query the Windows process-management interface for this exact process ID, including its command line; suppress lookup errors when the process is absent. |
| 9 | `if (-not $info -or -not $info.CommandLine) { return $false }` | Return false if no matching process or readable command line exists, because ownership cannot be established. |
| 10 | `if ($Name -eq 'backend') { return $info.CommandLine.Contains($Setup.python) -and $info.CommandLine.Contains('backend.main:app') -and $info.CommandLine.Contains('--port 8012') }` | For the backend, require the command line to contain the configured Python path, backend.main:app, and port 8012. All three checks must pass. |
| 11 | `return $info.CommandLine.Contains((Join-Path $ProjectRoot 'frontend\node_modules\vite\bin\vite.js'))` | For the frontend branch, require the command line to contain this project's installed Vite launcher path. The caller supplies frontend as the service name. |
| 12 | `}` | Close the process-identification function. |
| 13 | `function Find-WorkspaceListener([string]$Name, [int]$Port) {` | Define a helper that finds a listening process for a named service and integer TCP port. |
| 14 | `$listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)` | Collect TCP listeners on that port into an array. Listen means the socket is accepting incoming connections; lookup errors are suppressed. |
| 15 | `if (-not $listeners.Count) { return $null }` | Return null when there are no listeners, signaling that the caller should start the service. |
| 16 | `$serviceId = $listeners[0].OwningProcess` | Take the process ID that owns the first matching listener. |
| 17 | `if (-not (Test-WorkspaceProcess $serviceId $Name)) { throw "Port $Port is occupied by another application." }` | Check that the listener belongs to this workspace; throw an error if another application occupies the requested port. |
| 18 | `return Get-Process -Id $serviceId` | Return the Windows Process object for the verified listener. |
| 19 | `}` | Close the listener-discovery function. |
| 20 | `function New-ProcessRecord($Process, [string]$Name) {` | Define a helper that converts a live Process object and service name into a record suitable for JSON storage. |
| 21 | `return @{name=$Name; id=$Process.Id; started_ticks=$Process.StartTime.ToUniversalTime().Ticks.ToString()}` | Return a hashtable containing the service name, process ID, and UTC start-time ticks as text. The start time helps detect later reuse of the same process ID. |
| 22 | `}` | Close the process-record creation function. |
| 23 | `function Stop-RecordedProcess($Record) {` | Define a helper that safely attempts to stop a service described by a saved process record. |
| 24 | `$process = Get-Process -Id $Record.id -ErrorAction SilentlyContinue` | Look up the recorded process ID; suppress the error if the process has already exited. |
| 25 | `if ($process -and $Record.started_ticks -and $process.StartTime.ToUniversalTime().Ticks.ToString() -eq $Record.started_ticks -and (Test-WorkspaceProcess $Record.id $Record.name)) { Stop-Process -Id $Record.id }` | Stop the process only if it exists, has a saved start time, still has that exact start time, and still passes this project's ownership check. This guards against killing an unrelated process that reused an ID. |
| 26 | `}` | Close the recorded-process stopping function. |
| 27 | `function Wait-Http([string]$Url) {` | Define an HTTP readiness helper that receives a URL. |
| 28 | `$deadline = [DateTime]::UtcNow.AddSeconds(25)` | Set a deadline approximately 25 seconds from the current UTC time. |
| 29 | `do {` | Begin a do/while retry loop, which always performs at least one attempt. |
| 30 | `try { if ((Invoke-WebRequest $Url -TimeoutSec 2 -UseBasicParsing).StatusCode -eq 200) { return } } catch {}` | Request the URL with a two-second timeout; return immediately on HTTP 200. Ignore individual connection/status failures so startup can continue polling. |
| 31 | `Start-Sleep -Milliseconds 350` | Pause 350 milliseconds between attempts to avoid sending requests continuously. |
| 32 | `} while ([DateTime]::UtcNow -lt $deadline)` | Repeat while the deadline has not been reached. An in-progress request can make the total wait slightly longer than 25 seconds. |
| 33 | `throw "Service did not become ready: $Url. Check .runtime log files and PostgreSQL availability."` | Throw a readiness error after timeout, directing the developer to the runtime logs and PostgreSQL availability. |
| 34 | `}` | Close the HTTP readiness function. |

**Practical effects and limitations:** These helpers use Windows process and TCP APIs. Ownership is inferred from command-line text, not a cryptographic identity. The backend port is fixed at 8012 here; changing the launch port also requires changing this check. Discovery checks the first listener returned for a port. Process-ID plus start-time checks reduce accidental termination, but do not eliminate every possible race. No helper stops PostgreSQL.

### `scripts/configure.py`

Prepare the project's private environment file when one does not already exist. It can reuse the parent project's database connection while generating a separate JWT signing secret for this standalone demonstration.

| Line | Code | Explanation |
| --- | --- | --- |
| 1 | `"""Generate a separate local signing secret; reuse only the configured PostgreSQL connection."""` | Describe the script's purpose in a module docstring: generate a separate signing secret and reuse only the PostgreSQL connection setting. |
| 2 | `import secrets` | Import Python's secrets module, which provides random values suitable for security-sensitive tokens. |
| 3 | `from pathlib import Path` | Import Path for clear filesystem path construction and file operations. |
| 4 | `from dotenv import dotenv_values` | Import dotenv_values, which reads key/value settings from an environment file into a dictionary without printing them. |
| 7 | `root = Path(__file__).resolve().parents[1]` | Resolve this file's absolute path and select its second parent: configure.py is inside scripts, and this selects the standalone root directory. |
| 8 | `destination = root / ".env"` | Set the output destination to the private .env file in the project root. |
| 9 | `if not destination.exists():` | Run the configuration-generation block only when that destination file is absent. |
| 10 | `parent_configuration = root.parent / ".env"` | Point to the parent project's .env file, which may contain an existing database connection. |
| 11 | `connection = dotenv_values(parent_configuration).get("DATABASE_URL") if parent_configuration.exists() else None` | If that parent file exists, read its DATABASE_URL setting; otherwise use None. The script copies no other parent settings. |
| 12 | `if not connection:` | Check whether a nonempty database connection string was found. |
| 13 | `raise SystemExit("Copy .env.example to .env and configure PostgreSQL and a random JWT_SECRET first.")` | Exit with an instruction to configure .env manually if no connection is available. A message passed to SystemExit also produces an unsuccessful exit status. |
| 14 | `destination.write_text("\n".join([` | Start writing a newline-joined list of environment settings to the destination file. |
| 15 | `f"DATABASE_URL={connection}", "DATABASE_SCHEMA=resq_week1",` | Include the reused connection and explicitly isolate this demonstration's database tables in the resq_week1 schema. |
| 16 | `f"JWT_SECRET={secrets.token_hex(48)}", "JWT_EXPIRE_MINUTES=30",` | Generate a fresh 48-byte random secret encoded as 96 hexadecimal characters, and configure a 30-minute JWT lifetime. |
| 17 | `"CORS_ORIGINS=http://127.0.0.1:5175,http://localhost:5175", "",` | Allow browser requests from the two local frontend origins. The final empty string gives the written file a trailing newline. |
| 18 | `]), encoding="utf-8")` | Close the list, join, and write call, saving the text in UTF-8 encoding. |
| 19 | `print("Local authentication configuration ready. Secrets were not printed.")` | Print a status message that does not reveal the connection string or signing secret. |

**Practical effects and limitations:** If .env already exists, this script preserves it and prints the ready message without validating its values. Validation and database access happen later in application settings/startup and seeding. The parent file must be readable and contain DATABASE_URL for automatic generation. This explanation describes that code without opening either private environment file. python-dotenv is used here but is supplied indirectly through pydantic-settings rather than listed as its own pinned requirement.

### `scripts/setup.ps1`

Install dependencies, create local configuration, provision demonstration accounts, and save the Python executable for later start/stop operations. This is an explicit setup operation, not something the line-by-line documentation runs.

| Line | Code | Explanation |
| --- | --- | --- |
| 1 | `param([switch]$SkipInstall, [string]$PythonCommand = 'python')` | Declare optional parameters: -SkipInstall skips dependency installation, and -PythonCommand selects the Python command used to create a virtual environment; its default is python. |
| 2 | `$ErrorActionPreference = 'Stop'` | Stop the script on PowerShell errors. |
| 3 | `$ProjectRoot = Split-Path -Parent $PSScriptRoot` | Find the project root from the parent of the scripts directory. |
| 4 | `Set-Location -LiteralPath $ProjectRoot` | Change the current working directory to the project root so relative paths and Python module imports resolve consistently. |
| 5 | `New-Item -ItemType Directory -Path '.runtime\tmp' -Force \| Out-Null` | Create .runtime/tmp if necessary; -Force permits an existing directory, and Out-Null suppresses the directory object normally printed. |
| 6 | `$env:TEMP = Join-Path $ProjectRoot '.runtime\tmp'` | Set this PowerShell process's TEMP environment variable to that project-local temporary directory. |
| 7 | `$env:TMP = $env:TEMP` | Set TMP to the same directory so child tools using either temporary-directory variable receive the same location. |
| 8 | `function Assert-Exit([string]$Operation) { if ($LASTEXITCODE -ne 0) { throw "$Operation failed (exit $LASTEXITCODE)." } }` | Define an external-command success check: if the previous program's $LASTEXITCODE is not zero, throw an error naming the failed operation and its exit code. |
| 9 | `$pythonPath = Join-Path $ProjectRoot '.venv\Scripts\python.exe'` | Choose the project's own Windows virtual-environment Python executable as the initial interpreter path. |
| 10 | `if (-not $SkipInstall) {` | Enter the normal installation path unless -SkipInstall was supplied. |
| 11 | `if (-not (Test-Path -LiteralPath $pythonPath)) { & $PythonCommand -m venv .venv; Assert-Exit 'Virtual environment setup' }` | If the local interpreter is absent, invoke the chosen Python command to create .venv, then immediately check whether that external command succeeded. |
| 12 | `& $pythonPath -m pip install -r requirements.txt --disable-pip-version-check` | Use the chosen environment's Python to install the pinned requirements. The -m form invokes pip through that exact interpreter; the final option disables pip's version-update notice. |
| 13 | `Assert-Exit 'Python dependency installation'` | Abort setup if Python dependency installation returned a nonzero exit code. |
| 14 | `Push-Location -LiteralPath 'frontend'` | Temporarily change to the frontend directory, saving the previous location on PowerShell's location stack. |
| 15 | `try { & npm.cmd ci --no-audit --no-fund; Assert-Exit 'Frontend dependency installation' } finally { Pop-Location }` | Install frontend packages with npm ci and check success. Disable audit/funding output, and restore the previous directory in finally even if installation fails. |
| 16 | `} elseif (-not (Test-Path -LiteralPath $pythonPath)) {` | Otherwise, when installation is skipped and the local interpreter is missing, enter the fallback interpreter-selection block. |
| 17 | `$pythonPath = Join-Path (Split-Path -Parent $ProjectRoot) '.venv\Scripts\python.exe'` | Point to the parent project's .venv Python executable for a development environment reuse. |
| 18 | `if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Run setup without -SkipInstall to install dependencies.' }` | Stop if the fallback interpreter also does not exist and instruct the developer to run a normal setup. |
| 19 | `}` | Close the installation/fallback conditional. |
| 20 | `& $pythonPath -m scripts.configure` | Run scripts.configure as a Python module using the selected interpreter to prepare the local .env if needed. |
| 21 | `Assert-Exit 'Local configuration setup'` | Check the configuration script's exit code before continuing. |
| 22 | `& $pythonPath -m backend.seed` | Run backend.seed as a Python module to provision local demonstration accounts and initialize the required authentication storage. |
| 23 | `Assert-Exit 'Authentication account provisioning (PostgreSQL must be running)'` | Check seeding success and explicitly identify PostgreSQL availability as a requirement when it fails. |
| 24 | `@{python=$pythonPath} \| ConvertTo-Json \| Set-Content -LiteralPath '.runtime\setup.json' -Encoding utf8` | Write a JSON object containing the selected Python path to .runtime/setup.json in UTF-8, allowing common.ps1 to load it later. |
| 25 | `Write-Host 'ResQ Week 1 setup complete. Sign-in details: .runtime/demo-accounts.json'` | Announce completion and identify the private runtime file containing the generated demonstration sign-in details; print the file location, not its contents. |
| 26 | `Write-Host 'Run .\scripts\start.ps1 to open the authentication demo on port 5175.'` | Print the next command and frontend port. Starting services is a separate step. |

**Practical effects and limitations:** A normal setup requires an available Python command, npm/Node, and running PostgreSQL. npm ci relies on the committed lockfile matching package.json. -SkipInstall does not install or verify dependencies, and frontend node_modules must already exist. The script changes the current PowerShell location and TEMP/TMP variables. It provisions authentication accounts, so setup is a database-writing operation. It does not start or stop the PostgreSQL service.

### `scripts/start.ps1`

Start or reuse this demonstration's backend and frontend, wait for HTTP readiness, and persist enough process metadata for stop.ps1 to identify the services safely.

| Line | Code | Explanation |
| --- | --- | --- |
| 1 | `. (Join-Path $PSScriptRoot 'common.ps1')` | Dot-source common.ps1, executing its setup-file checks and importing its shared variables/functions into this script's scope. |
| 2 | `Set-Location -LiteralPath $ProjectRoot` | Change the working directory to the standalone project root. |
| 3 | `$processFile = Join-Path $RuntimePath 'processes.json'` | Build the path to processes.json, which stores backend/frontend process records. |
| 4 | `$records = @()` | Create an empty array for all services tracked by this start operation, including services it reuses. |
| 5 | `$created = @()` | Create an empty array for services newly created by this start operation, used for rollback on an error. |
| 6 | `try {` | Begin a try block around service startup so a later failure can attempt cleanup. |
| 7 | `$backend = Find-WorkspaceListener 'backend' 8012` | Find the backend listener on port 8012; reject an unrelated process occupying the port. |
| 8 | `if (-not $backend) {` | Enter backend startup only if no matching backend listener exists. |
| 9 | `$python = $Setup.python` | Read the Python executable saved by setup. |
| 10 | `$launcher = Start-Process -FilePath $python -ArgumentList @('-m','uvicorn','backend.main:app','--host','127.0.0.1','--port','8012') -WorkingDirectory $ProjectRoot -RedirectStandardOutput (Join-Path $RuntimePath 'backend.log') -RedirectStandardError (Join-Path $RuntimePath 'backend-error.log') -WindowStyle Hidden -PassThru` | Launch Uvicorn with backend.main:app using that Python, bind to loopback port 8012, run from the project root, redirect normal/error output into separate runtime logs, hide the helper window, and return a Process object into $launcher. |
| 11 | `Wait-Http 'http://127.0.0.1:8012/health'` | Poll the backend /health URL until it returns HTTP 200 or readiness times out. That endpoint also checks database availability. |
| 12 | `# Windows venv's python.exe is a redirector. Record the actual listener.` | Explain why the launcher process is not assumed to be the eventual listening process: Windows virtual-environment Python can redirect to another executable. |
| 13 | `$backend = Find-WorkspaceListener 'backend' 8012` | Find the actual backend listener after startup instead of saving only the initial launcher process. |
| 14 | `if (-not $backend) { throw 'The backend listener was not found.' }` | Fail if the backend still has no verified listener. |
| 15 | `$created += New-ProcessRecord $backend 'backend'` | Add the newly created backend's process record to the cleanup array. |
| 16 | `} else { Wait-Http 'http://127.0.0.1:8012/health' }` | When reusing a backend, still check its /health response before accepting it. |
| 17 | `$records += New-ProcessRecord $backend 'backend'` | Add the backend process record to the full tracking array, whether it was launched or reused. |
| 18 | `$records \| ConvertTo-Json -AsArray \| Set-Content -LiteralPath $processFile -Encoding utf8` | Serialize the tracking array as a JSON array even when it has only one item, and save it immediately. This preserves backend tracking before frontend startup. |
| 20 | `$frontend = Find-WorkspaceListener 'frontend' 5175` | Find the frontend listener on port 5175 and reject an unrelated listener occupying that port. |
| 21 | `if (-not $frontend) {` | Enter frontend startup if no matching Vite listener exists. |
| 22 | `$node = (Get-Command node.exe).Source` | Locate node.exe through PowerShell command discovery and store its resolved executable path. |
| 23 | `$vite = '"' + (Join-Path $ProjectRoot 'frontend\node_modules\vite\bin\vite.js') + '"'` | Build the absolute path to the installed Vite JavaScript launcher, surrounded by quote characters so paths containing spaces remain usable in the process arguments. |
| 24 | `$launcher = Start-Process -FilePath $node -ArgumentList @($vite) -WorkingDirectory (Join-Path $ProjectRoot 'frontend') -RedirectStandardOutput (Join-Path $RuntimePath 'frontend.log') -RedirectStandardError (Join-Path $RuntimePath 'frontend-error.log') -WindowStyle Hidden -PassThru` | Run that Vite launcher through Node from the frontend directory, redirect its normal/error output to runtime log files, hide its window, and obtain the initial Process object. |
| 25 | `Wait-Http 'http://127.0.0.1:5175/'` | Poll the frontend root URL until it responds with HTTP 200 or times out. |
| 26 | `$frontend = Find-WorkspaceListener 'frontend' 5175` | Find and identify the actual Vite listener after readiness. |
| 27 | `if (-not $frontend) { throw 'The frontend listener was not found.' }` | Fail if a matching frontend listener cannot be found. |
| 28 | `$created += New-ProcessRecord $frontend 'frontend'` | Add the newly created frontend process record to the cleanup array. |
| 29 | `} else { Wait-Http 'http://127.0.0.1:5175/' }` | When reusing a frontend, still wait for its root page to return HTTP 200. |
| 30 | `$records += New-ProcessRecord $frontend 'frontend'` | Add the frontend record to the full tracking array. |
| 31 | `$records \| ConvertTo-Json -AsArray \| Set-Content -LiteralPath $processFile -Encoding utf8` | Save the final JSON array containing both tracked services. |
| 32 | `if (-not $created.Count) { Write-Host 'Existing project services reused.' }` | If no service was newly created, print that existing project services were reused. |
| 33 | `Write-Host 'ResQ Week 1: http://127.0.0.1:5175'` | Print the frontend address for the developer to open. |
| 34 | `Write-Host 'API documentation: http://127.0.0.1:8012/docs'` | Print the backend's generated API documentation address. |
| 35 | `} catch {` | End the normal startup block and begin the error handler. |
| 36 | `foreach ($record in $created) { Stop-RecordedProcess $record }` | Attempt to stop each newly created, recorded service using the ownership/start-time checks. Reused services are absent from this cleanup array. |
| 37 | `throw` | Rethrow the original startup error so the command reports failure. |
| 38 | `}` | Close the catch block. |

**Practical effects and limitations:** This script launches the Vite development server, not a production deployment. Backend network binding is explicitly 127.0.0.1; frontend binding/port come from Vite configuration. It prints URLs but does not open a browser. Readiness establishes HTTP 200, not successful end-to-end login behavior. Process records include reused services, so stop.ps1 can later stop those services too. A new service is added to the cleanup array only after readiness/listener discovery; if startup fails earlier, an unrecorded process can remain running. Failed startup can also leave an older/partial processes.json; identity checks help stop ignore stale records. $launcher is intentionally not the stored service identity. -AsArray requires PowerShell 7, matching README guidance.

### `scripts/stop.ps1`

Stop the backend/frontend services represented by saved process records, subject to the shared ownership checks. It does not stop unrelated applications or the shared PostgreSQL service.

| Line | Code | Explanation |
| --- | --- | --- |
| 1 | `. (Join-Path $PSScriptRoot 'common.ps1')` | Dot-source common.ps1 to load runtime paths and the safe-stop helper; this also requires setup.json to exist. |
| 2 | `$recordFile = Join-Path $RuntimePath 'processes.json'` | Locate the process-record JSON file in .runtime. |
| 3 | `if (Test-Path -LiteralPath $recordFile) {` | Only enter the stopping block if a process-record file exists. |
| 4 | `foreach ($record in (Get-Content -LiteralPath $recordFile -Raw \| ConvertFrom-Json)) { Stop-RecordedProcess $record }` | Read and parse the recorded JSON, loop through every service record, and pass each one to the helper that verifies process ID, start time, and workspace ownership before stopping it. |
| 5 | `Remove-Item -LiteralPath $recordFile` | Remove the process-record file after the loop completes. |
| 6 | `}` | Close the conditional block. |
| 7 | `Write-Host 'Recorded ResQ authentication services stopped.'` | Print a completion message. This message also appears if no process-record file existed. |

**Practical effects and limitations:** Stopping is limited to saved records; services launched outside the tracking script or left unrecorded after a startup failure may continue running. Stale/nonmatching records are skipped by Stop-RecordedProcess. A tracked service may have been reused by start.ps1 rather than newly launched. The final message reports completion of the stopping attempt, not an independent port/readiness check.

### `requirements.txt`

Pin the Python packages installed by setup.ps1. The equality operator in each line selects a specific release for repeatable installation. These lines are dependency declarations, not Python statements.

| Line | Code | Explanation |
| --- | --- | --- |
| 1 | `fastapi==0.119.1` | Install FastAPI, the framework defining API routes, dependency injection, request validation integration, and generated API documentation. |
| 2 | `uvicorn==0.38.0` | Install Uvicorn, the ASGI HTTP server that runs the FastAPI application. |
| 3 | `SQLAlchemy==2.0.44` | Install SQLAlchemy, which maps account/session models to tables and supplies database sessions and queries. |
| 4 | `psycopg[binary]==3.2.12` | Install Psycopg 3 with its binary extra: the PostgreSQL driver and prebuilt binary support used by the postgresql+psycopg connection URL. |
| 5 | `pydantic==2.12.3` | Install Pydantic, which defines and validates typed request/response schemas. |
| 6 | `pydantic-settings==2.11.0` | Install pydantic-settings, which loads validated application settings from environment variables and environment files. |
| 7 | `PyJWT==2.10.1` | Install PyJWT, which creates and verifies signed JSON Web Tokens used by authentication. |
| 8 | `pwdlib[argon2]==0.3.0` | Install pwdlib with its Argon2 extra, providing the password-hashing implementation used for storing and checking password hashes. |
| 9 | `email-validator==2.3.0` | Install email-validator, which supports the email address validation used by Pydantic's email fields. |
| 10 | `httpx==0.28.1` | Install HTTPX, the HTTP client needed by the FastAPI/Starlette test client in the API tests. |
| 11 | `pytest==8.4.2` | Install pytest, the test runner used by the backend authentication test suite. |

**Practical effects and limitations:** The requirements include test dependencies as well as runtime dependencies. Extras such as [binary] and [argon2] request optional dependency groups. This file pins direct packages, not every transitive dependency. It does not install Node/frontend packages or PostgreSQL itself. These versions are the versions declared in this checkout, not a claim that they are the newest available releases.

### `pytest.ini`

Provide default pytest settings for the backend test suite.

| Line | Code | Explanation |
| --- | --- | --- |
| 1 | `[pytest]` | Open the pytest configuration section of this INI-format file. |
| 2 | `testpaths = backend/tests` | Tell pytest where to look by default when no explicit test paths are supplied: backend/tests. |
| 3 | `addopts = -q` | Add -q to the default command options so test output is quieter and less verbose. |

**Practical effects and limitations:** Explicit command-line test paths can override default discovery. This file does not define the test database; that is configured in the test code. Quiet output still reports failures.

### `.env.example`

Show the names and shape of local configuration settings that a developer must replace in their private .env. Placeholder values are examples, not usable private credentials.

| Line | Code | Explanation |
| --- | --- | --- |
| 1 | `# A separate schema keeps ResQ authentication demo apart from the shared app.` | Explain that the demonstration uses a separate database schema so its tables can be kept apart from the shared app's tables. |
| 2 | `DATABASE_URL=postgresql+psycopg://resq:YOUR_DATABASE_PASSWORD@127.0.0.1:5441/resq_week1` | Provide an example SQLAlchemy PostgreSQL connection URL: psycopg driver, database user resq, a password placeholder, loopback host, port 5441, and database resq_week1. Replace the placeholder and adapt the connection to the actual local database. |
| 3 | `DATABASE_SCHEMA=resq_week1` | Set the namespace for this module's authentication tables to resq_week1. |
| 4 | `JWT_SECRET=REPLACE_WITH_AT_LEAST_32_RANDOM_CHARACTERS` | Show where a randomly generated signing secret must be placed. The text shown is a replacement instruction; it must not be used as the actual secret. |
| 5 | `JWT_EXPIRE_MINUTES=30` | Set the access-token lifetime to 30 minutes. |
| 6 | `CORS_ORIGINS=http://127.0.0.1:5175,http://localhost:5175` | Allow browser requests from the frontend at either 127.0.0.1 or localhost on port 5175. These are different browser origins even when they point to the same machine. |

**Practical effects and limitations:** This file is a template; editing it alone does not configure a running app that reads .env. PostgreSQL must already exist and the selected user needs schema-creation rights for automatic setup. A separate schema separates table namespaces; it does not by itself create a separate PostgreSQL server or database-user permission boundary. CORS settings govern browser cross-origin access and do not replace authentication or server-side role checks. No private .env was read while writing this explanation.

### `.gitignore`

Tell Git which local/generated files should remain untracked. Each pattern is evaluated by Git rather than executed by Python or PowerShell.

| Line | Code | Explanation |
| --- | --- | --- |
| 1 | `.env` | Ignore environment files named .env so local connection settings and signing secrets are not accidentally added as new files. |
| 2 | `.venv/` | Ignore directories named .venv containing installed Python environments. |
| 3 | `.runtime/` | Ignore .runtime directories containing local account details, service metadata, logs, and verification artifacts. |
| 4 | `__pycache__/` | Ignore Python bytecode-cache directories. |
| 5 | `*.py[cod]` | Ignore files with .pyc, .pyo, or .pyd suffixes; the bracket expression matches one of c, o, or d. |
| 6 | `.pytest_cache/` | Ignore pytest's cache directories. |
| 7 | `.coverage` | Ignore the .coverage data file generated by coverage tools. |
| 8 | `node_modules/` | Ignore installed Node dependency directories. |
| 9 | `frontend/dist/` | Ignore the frontend's generated production build output. |
| 10 | `*.log` | Ignore files whose names end with .log. |
| 11 | `*.db` | Ignore files whose names end with .db, such as local SQLite database files. |
| 12 | `test-results/` | Ignore generated test-results directories. |
| 13 | `playwright-report/` | Ignore Playwright browser-test report directories. |

**Practical effects and limitations:** Git ignore rules prevent untracked matching files from appearing in normal add/status workflows; they do not remove already tracked files, encrypt files, or restrict filesystem access. The frontend lockfile stays trackable so npm ci can install repeatable dependencies. Source files, tests, and .env.example remain visible to Git.

### `backend/__init__.py`

Mark the backend directory as a regular Python package and document its role.

| Line | Code | Explanation |
| --- | --- | --- |
| 1 | `"""ResQ Kerala Week 1 API."""` | Set the package docstring describing this project's Week 1 API; this string documents the package and performs no server startup. |

**Practical effects and limitations:** Importing this initializer alone does not create the FastAPI app, connect to the database, or start Uvicorn.

### `backend/database/__init__.py`

Mark the database helper directory as a regular Python package.

| Line | Code | Explanation |
| --- | --- | --- |
| 1 | `"""Database setup and session management."""` | Set a package docstring naming its responsibilities: database setup and session management. |

**Practical effects and limitations:** The actual engine, session, and table initialization logic lives in the database modules, not this docstring.

### `backend/models/__init__.py`

Provide convenient package-level imports for the account role and SQLAlchemy models.

| Line | Code | Explanation |
| --- | --- | --- |
| 1 | `from .user import Role, TokenSession, User` | Use a relative import to expose Role, TokenSession, and User from the sibling user.py module through backend.models. |
| 3 | `__all__ = ["Role", "TokenSession", "User"]` | Declare the intended public export names, including names used by from backend.models import *. This is an export list, not an access-control mechanism. |

**Practical effects and limitations:** Importing the models executes their module definitions and makes the classes available; it does not by itself insert accounts or create tables. Re-exporting these names avoids forcing every caller to know the underlying module path.

### `backend/routers/__init__.py`

Mark the HTTP router directory as a regular Python package.

| Line | Code | Explanation |
| --- | --- | --- |
| 1 | `"""HTTP route modules."""` | Set a docstring identifying this package as the place for HTTP route modules. |

**Practical effects and limitations:** Routes become part of the app when the application imports and includes their routers; this initializer does not register routes.

### `backend/schemas/__init__.py`

Mark the API schema directory as a regular Python package.

| Line | Code | Explanation |
| --- | --- | --- |
| 1 | `"""Validated API input and output contracts."""` | Describe the package's validated request and response contracts in its docstring. |

**Practical effects and limitations:** Actual Pydantic fields and validators are defined in auth.py; this initializer defines no schemas itself.

### `backend/services/__init__.py`

Mark the business-rule directory as a regular Python package.

| Line | Code | Explanation |
| --- | --- | --- |
| 1 | `"""Week 1 business rules."""` | Document that the package contains the Week 1 business rules. |

**Practical effects and limitations:** Business operations live in service modules such as auth_service.py; this initializer does not register or log in a user.

### `backend/utils/__init__.py`

Mark the reusable-helper directory as a regular Python package.

| Line | Code | Explanation |
| --- | --- | --- |
| 1 | `"""Authentication, authorization and validation helpers."""` | Document the package's authentication, authorization, and validation helper responsibilities. |

**Practical effects and limitations:** Password hashing, JWT validation, and role checks run through their utility functions, not through this package docstring.

### `backend/schemas/auth_schema.py`

Maintain the authentication schema import path named in the weekly assignment while keeping the schema definitions in one place, auth.py.

| Line | Code | Explanation |
| --- | --- | --- |
| 1 | `from .auth import AuthResponse, LoginRequest, RegisterRequest` | Re-export the existing AuthResponse, LoginRequest, and RegisterRequest classes from the sibling auth.py module. These are the same class objects, not copied schema definitions. |
| 3 | `__all__ = ["AuthResponse", "LoginRequest", "RegisterRequest"]` | List the three supported public exports, including what wildcard imports from this module expose. |

**Practical effects and limitations:** This compatibility module prevents duplicate validation logic. Changing a definition in auth.py automatically affects code importing the class through auth_schema.py. It defines no endpoints or separate validation rules.

### `backend/schemas/user_schema.py`

Provide a compatibility import path for the public account response schema.

| Line | Code | Explanation |
| --- | --- | --- |
| 1 | `from .auth import UserResponse` | Re-export UserResponse from auth.py, allowing callers to import it from backend.schemas.user_schema. |
| 3 | `__all__ = ["UserResponse"]` | Declare UserResponse as the module's intended public export. |

**Practical effects and limitations:** The actual response fields, serialization settings, and exclusion of password hashes are controlled by UserResponse in auth.py. This file does not add fields or query the database.

## Existing project documentation

The historical standalone `README.md` was the run-and-demo guide: it mapped authentication responsibilities to files, lists prerequisite software and startup commands, explains the separate schema/ports, and outlines the registration/login/role/logout demonstration. Its verification paragraph records checks reported for 6 October 2026; reading that paragraph does not rerun those checks.

`docs/week1-tasks.md` defines ownership and integration scope. It records the assignment reference, names the auth responsibilities, gives the API handoff contract and status codes, explains PostgreSQL storage and the isolated test database, and identifies shared files that need coordination in the full project.

These prose files are documentation, not executable source, so they are explained by role rather than annotated sentence by sentence. The references they contain to the weekly slides and broader project discussion describe assignment provenance; those external documents were not reopened for this support-file explanation.

## Tests

### `backend/tests/test_auth.py`

This file exercises the real FastAPI authentication and role-permission routes through TestClient. It is verification code, not an application feature that runs for visitors. A test passes only when every assertion inside it is true; a failed assertion tells pytest the behavior does not match the expectation.

Pytest finds functions whose names start with test_. The api parameter asks pytest to supply the api fixture automatically. That fixture creates three synthetic accounts in a new in-memory SQLite database, replaces the app's get_db dependency, provides a Harness, and restores the dependency overrides and disposes the database afterwards. A yield fixture has setup before yield and teardown afterwards. A session-scoped fixture shares the expensive password hash across the run; the database fixture still runs separately for each collected test case.

A parametrization decorator expands one function into several cases with different inputs. This file has 16 test functions and 27 collected cases. The workspace matrix also makes nine individual role-to-route comparisons inside its three cases. An HTTP assertion checks the public API result; direct SQLAlchemy assertions separately check stored side effects.

#### Scenario coverage

| Area | Cases | Behavior checked |
| --- | ---: | --- |
| New citizen registration | 1 | Name/email normalization, citizen-only role, no password fields in user JSON, working stored hash, immediately usable bearer token. |
| Duplicate email | 1 | Normalized duplicates return 409 and leave one existing account. |
| Attempted privilege assignment | 3 | Extra role or team_id fields return 422 and create no account. |
| Invalid registration | 4 | Blank name, malformed email, short password, and numeric password return 422 without adding users. |
| Password whitespace | 1 | Leading/trailing password spaces remain meaningful characters. |
| Successful login | 1 | Email normalization, bearer response, expected user role. |
| Failed login | 2 | Wrong password and nonexistent email return 401 with a Bearer challenge and create no session. |
| Logout isolation | 1 | Logout revokes only the current session; another session stays usable. |
| Persisted session expiry or deletion | 2 | Existing tokens fail when their database session expires or disappears. |
| Account deactivation | 1 | Existing token and new login fail for an inactive account. |
| Missing/malformed auth on protected GET routes | 4 | Current-user and all three workspace routes reject missing or malformed credentials. |
| Logout without authentication | 1 | Logout requires a bearer session. |
| Workspace role matrix | 3 | Each role enters its own workspace and receives 403 for either other role, including admin. |
| Live role change | 1 | The same token follows the user's updated role in the database. |
| Healthy database | 1 | Health route reports ok and connected for the fixture database. |

#### What the isolation and coverage mean

The environment assignments happen before importing the application. In the intended isolated pytest process this selects SQLite instead of the PostgreSQL runtime database and supplies a public test signing secret. Each api fixture then creates its own SQLite engine and redirects request dependencies to it. Entering TestClient also runs the application's lifespan against a separate app-level in-memory engine. Both are ephemeral, but only the fixture engine contains the three seeded test accounts.

The module changes process environment variables and does not restore them. Its isolation relies on these assignments preceding the application's cached settings and engine initialization. If other test modules import/configure the app earlier in the same process, those earlier cached objects can defeat this assumption. This source-order limitation does not mean the ordinary isolated invocation accesses PostgreSQL.

SQLite verifies the request handling and ORM logic here; it does not verify PostgreSQL schema creation, psycopg connectivity, PostgreSQL-specific semantics, production connection settings, concurrent registration races, or deployment behavior. The expiry test changes the persisted session's expires_at; it does not independently construct a cryptographically valid JWT whose exp claim is already expired. The malformed-token test likewise does not separately cover tampering, issuer/audience mismatch, every missing claim, or a validly signed token with inconsistent session ownership.

The suite does not exercise browser forms/navigation, CORS/security-response-header assertions, database outage responses, startup failure, HTTPS, rate limiting, migration behavior, or a complete incident/team workflow. Foreign keys are enabled in setup, but no test deliberately triggers a foreign-key violation. Those are coverage boundaries, not claims that the corresponding implementation necessarily fails.

#### Physical line-by-line explanation

Line numbers match the current source. Every nonblank physical line is included; blank lines separate logical blocks and do not execute any instruction. Multiline request bodies and decorators are explained one physical line at a time.

| Line | Code | Explanation |
| ---: | --- | --- |
| 1 | `"""ResQ Week 1 authentication and role-permission API checks.` | Start the module docstring: this file describes authentication and role-permission API tests for ResQ Week 1 slice. |
| 3 | `Every test has a fresh in-memory database. These checks never read or change the` | Document that each test case receives a fresh in-memory database through the api fixture. This applies to each parametrized case too. |
| 4 | `full project's accounts, incident reports, team assignments, or demo database.` | Continue the isolation statement: fixture requests use synthetic accounts rather than the full project's operational data. |
| 5 | `"""` | Close the module docstring; the text above is documentation, not executable assertions. |
| 7 | `import os` | Import os so the test module can set process environment variables before application imports. |
| 8 | `from dataclasses import dataclass, field` | Import dataclass to generate the Harness initializer and field to create an independent token-cache dictionary for each Harness. |
| 9 | `from datetime import datetime, timedelta, timezone` | Import timezone-aware timestamps and timedelta, used to deliberately expire a persisted test session. |
| 11 | `os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"` | Set the application's database URL to an in-memory SQLite database before its configuration module is imported. No database file is created by this URL. |
| 12 | `os.environ["ALLOW_SQLITE_FOR_TESTS"] = "true"` | Enable the explicit test-only SQLite configuration exception; normal runtime configuration requires PostgreSQL. |
| 13 | `os.environ["JWT_SECRET"] = "resq-isolated-auth-tests-only-secret-2026"` | Set a public synthetic signing secret solely for this isolated test process. This value must never be reused as a deployment secret. |
| 15 | `import pytest` | Import pytest, which discovers test functions and provides fixtures and parametrization. |
| 16 | `from fastapi.testclient import TestClient` | Import FastAPI's synchronous TestClient, which invokes the ASGI app inside the process without starting Uvicorn or opening a browser. |
| 17 | `from sqlalchemy import create_engine, event, select` | Import SQLAlchemy tools: create_engine establishes database access, event installs connection hooks, and select constructs query statements. |
| 18 | `from sqlalchemy.orm import sessionmaker` | Import sessionmaker, a factory that creates ORM Session objects for the test engine. |
| 19 | `from sqlalchemy.pool import StaticPool` | Import StaticPool, which reuses one SQLite connection so all sessions for a fixture see the same in-memory database. |
| 21 | `from backend.database.connection import Base, get_db` | Import the application's declarative Base and its get_db dependency. Base carries table definitions; get_db is the function the fixture will override. |
| 22 | `from backend.main import app` | Import the real FastAPI app. The environment overrides above must run before this import initializes cached application settings and the engine. |
| 23 | `from backend.models import Role, TokenSession, User` | Import the real role enumeration and account/session ORM models, so tests exercise the application schema. |
| 24 | `from backend.utils.security import hash_password, verify_password` | Import the production password functions, so the fixture and assertions use the same Argon2-capable pwdlib implementation as the application. |
| 27 | `TEST_PASSWORD = "Synthetic-auth-pass!2026"` | Define a public synthetic password reused by test accounts. Sharing this fixture password saves setup work and carries no production credential. |
| 28 | `WORKSPACES = {` | Start the mapping from role values to the routes those roles should be allowed to open. |
| 29 | `    "citizen": "/api/workspaces/citizen",` | Map the citizen role value to the citizen workspace endpoint. |
| 30 | `    "admin": "/api/workspaces/admin",` | Map the admin role value to the admin workspace endpoint. |
| 31 | `    "response_team": "/api/workspaces/response-team",` | Map the response_team role value to the hyphenated response-team URL; database role spelling and URL spelling differ deliberately. |
| 32 | `}` | Close the workspace mapping. |
| 35 | `@dataclass` | Apply dataclass to generate a convenient constructor and representation for the Harness fields. |
| 36 | `class Harness:` | Define Harness, a small holder for each test's API client, session factory, account IDs, and cached bearer tokens. |
| 37 | `    client: TestClient` | Declare that client holds a TestClient. This annotation describes its intended type; it does not create a client here. |
| 38 | `    sessions: object` | Declare sessions as an object, containing the SQLAlchemy sessionmaker supplied by the fixture; the annotation is intentionally broad. |
| 39 | `    users: dict[str, int]` | Declare a dictionary mapping role strings to seeded integer user IDs. |
| 40 | `    token_cache: dict[str, str] = field(default_factory=dict)` | Create a new empty token-cache dictionary for each Harness using default_factory. A shared mutable class-level dictionary would leak tokens between harnesses. |
| 42 | `    def login(self, role: str) -> dict:` | Define a helper that signs in the seeded account for a supplied role and returns the decoded login JSON dictionary. |
| 43 | `        response = self.client.post("/api/auth/login", json={` | Start a POST request to the real login route, with a JSON request body. |
| 44 | `            "email": f"{role}@example.com", "password": TEST_PASSWORD,` | Build the seeded email address with an f-string and supply the shared synthetic password. |
| 45 | `        })` | Finish the request body and client call; response now contains the HTTP result. |
| 46 | `        assert response.status_code == 200, response.text` | Require a successful 200 login. If it fails, response.text becomes the assertion failure message for easier diagnosis. |
| 47 | `        return response.json()` | Decode the JSON response and return its token and user details to the caller. |
| 49 | `    def headers(self, role: str) -> dict[str, str]:` | Define a helper that returns HTTP Authorization headers for a seeded role. |
| 50 | `        if role not in self.token_cache:` | Check whether this Harness already has a bearer token for the role. |
| 51 | `            self.token_cache[role] = self.login(role)["access_token"]` | If needed, log in once, extract access_token from the response, and store it under the role key. |
| 52 | `        return {"Authorization": f"Bearer {self.token_cache[role]}"}` | Return an Authorization header in the standard Bearer token format; subsequent calls for the same role reuse that cached session. |
| 55 | `@pytest.fixture(scope="session")` | Register synthetic_password_hash as a session-scoped fixture: pytest computes it once for the whole test run, rather than repeating an expensive password hash per test. |
| 56 | `def synthetic_password_hash():` | Define the fixture function pytest calls when another fixture asks for synthetic_password_hash. |
| 57 | `    return hash_password(TEST_PASSWORD)` | Use the real password hashing function to generate the shared test password's encoded hash. |
| 60 | `@pytest.fixture` | Register api as a fixture. With no explicit scope, its scope is function, giving each collected test case fresh setup and teardown. |
| 61 | `def api(synthetic_password_hash):` | Define api and request the synthetic_password_hash fixture by parameter name; pytest resolves this dependency automatically. |
| 62 | `    test_engine = create_engine(` | Begin creation of a new engine exclusively for this fixture instance. |
| 63 | `        "sqlite+pysqlite:///:memory:",` | Use an in-memory SQLite URL. Each new fixture engine has isolated ephemeral database contents. |
| 64 | `        connect_args={"check_same_thread": False}, poolclass=StaticPool,` | Disable SQLite's same-thread check because TestClient can run app work in another thread; StaticPool shares the same connection across this fixture's sessions. This is test plumbing, not a general concurrency strategy. |
| 65 | `    )` | Finish engine creation. |
| 67 | `    @event.listens_for(test_engine, "connect")` | Register the following callback for each new DBAPI connection opened by this test engine. |
| 68 | `    def foreign_keys(connection, _record):` | Define the connection hook. connection is the underlying SQLite connection; _record is an unused SQLAlchemy pool record. |
| 69 | `        connection.execute("PRAGMA foreign_keys=ON")` | Enable SQLite foreign-key enforcement, which SQLite otherwise commonly leaves disabled. This enables constraints but no test here explicitly asserts a foreign-key failure. |
| 71 | `    Base.metadata.create_all(test_engine)` | Create tables for all ORM models registered with Base on this fixture engine. This uses metadata.create_all rather than a migration system. |
| 72 | `    sessions = sessionmaker(bind=test_engine, expire_on_commit=False)` | Create a session factory bound to the fixture engine. expire_on_commit=False keeps loaded attributes readable after a commit. |
| 73 | `    with sessions() as db:` | Open a short setup session; the with block closes it after seeding finishes. |
| 74 | `        accounts = [` | Start a list of three synthetic account model objects. |
| 75 | `            User(full_name="Test Citizen", email="citizen@example.com",` | Construct the citizen account with its test name and email address. |
| 76 | `                 role=Role.CITIZEN, password_hash=synthetic_password_hash),` | Assign its real citizen enum value and the shared synthetic password hash; close this User construction. |
| 77 | `            User(full_name="Test Admin", email="admin@example.com",` | Construct the admin account directly in the database for permission tests. |
| 78 | `                 role=Role.ADMIN, password_hash=synthetic_password_hash),` | Assign its admin role and the shared test hash. Seeding bypasses public registration, which deliberately cannot create privileged accounts. |
| 79 | `            User(full_name="Test Team Member", email="response_team@example.com",` | Construct the response-team member's synthetic account. |
| 80 | `                 role=Role.RESPONSE_TEAM, password_hash=synthetic_password_hash),` | Assign its response_team enum value and the same test hash. |
| 81 | `        ]` | Close the seeded account list. |
| 82 | `        db.add_all(accounts)` | Stage all three account objects for insertion in the session. |
| 83 | `        db.commit()` | Commit the seed data, persisting rows and populating generated user IDs. |
| 84 | `        user_ids = {user.role.value: user.id for user in accounts}` | Build a role-to-ID dictionary from the inserted objects. role.value retrieves strings such as citizen rather than the enum object. |
| 86 | `    def override_database():` | Define a replacement for the app's normal get_db dependency. |
| 87 | `        with sessions() as db:` | Open a new ORM Session bound to this test's SQLite engine for each dependency invocation. |
| 88 | `            yield db` | Yield the session to FastAPI and close it when the dependency finishes; this does not automatically commit application changes. |
| 90 | `    previous_overrides = app.dependency_overrides.copy()` | Save existing dependency overrides so this fixture can restore the app's prior state at teardown. |
| 91 | `    app.dependency_overrides[get_db] = override_database` | Replace requests' get_db dependency with the local test session provider. Route and nested permission dependencies now use the fixture database. |
| 92 | `    try:` | Start a try/finally region so cleanup runs even when a test or setup operation raises an exception. |
| 93 | `        with TestClient(app) as client:` | Enter TestClient as a context manager, which starts the app lifespan. The lifespan separately initializes the app-level engine selected by the earlier environment overrides; requests are still redirected to the fixture engine. |
| 94 | `            yield Harness(client, sessions, user_ids)` | Yield a Harness to the test. Pytest pauses the fixture here, runs the test, then resumes teardown; leaving the TestClient block runs app shutdown. |
| 95 | `    finally:` | Start unconditional cleanup after the test/client lifecycle. |
| 96 | `        app.dependency_overrides.clear()` | Clear dependency overrides introduced during this fixture's use. |
| 97 | `        app.dependency_overrides.update(previous_overrides)` | Restore the saved overrides, preserving any earlier app state rather than leaving the test database attached. |
| 98 | `        test_engine.dispose()` | Dispose the fixture engine and release its connection; its in-memory database goes away. |
| 101 | `def test_registration_creates_citizen_and_hashes_password(api):` | Define the test for successful registration, safe response serialization, password hashing, and immediate use of the registration token. |
| 102 | `    response = api.client.post("/api/auth/register", json={` | Send a registration POST with a valid JSON body. |
| 103 | `        "full_name": "  New Citizen  ", "email": " NEW@EXAMPLE.COM ",` | Supply padded name and mixed-case, padded email to exercise normalization. |
| 104 | `        "password": TEST_PASSWORD,` | Supply the valid synthetic password. |
| 105 | `    })` | Finish the registration request. |
| 106 | `    assert response.status_code == 201, response.text` | Require HTTP 201 Created; print the response body in the failure message if registration fails. |
| 107 | `    body = response.json()` | Decode the JSON response into body. |
| 108 | `    assert body["user"]["role"] == "citizen"` | Require a public registration to create the citizen role rather than a privileged account. |
| 109 | `    assert body["user"]["full_name"] == "New Citizen"` | Require leading/trailing spaces to be removed from the display name. |
| 110 | `    assert body["user"]["email"] == "new@example.com"` | Require email whitespace removal and lowercase normalization. |
| 111 | `    assert "password" not in body["user"] and "password_hash" not in body["user"]` | Require the nested public user response to contain neither a plaintext password field nor a password_hash field. This assertion concerns those response keys, not every possible disclosure channel. |
| 112 | `    with api.sessions() as db:` | Open a direct ORM session to inspect the stored registration row independently of the response. |
| 113 | `        user = db.scalar(select(User).where(User.email == "new@example.com"))` | Select the new account by normalized email and return its single User object. |
| 114 | `        assert user.password_hash != TEST_PASSWORD` | Require the stored password_hash string to differ from plaintext; this alone is weaker than proving a particular hashing algorithm. |
| 115 | `        assert verify_password(TEST_PASSWORD, user.password_hash)` | Require the production verifier to recognize the submitted password against the stored hash, confirming a functional encoded password. |
| 116 | `    headers = {"Authorization": f"Bearer {body['access_token']}"}` | Build bearer authorization from the token returned by registration. |
| 117 | `    assert api.client.get("/api/users/me", headers=headers).json()["id"] == body["user"]["id"]` | Call the protected /api/users/me route and require its returned ID to match the newly registered user. This proves the registration token works; the line does not separately assert the response status. |
| 120 | `def test_duplicate_email_is_case_insensitive(api):` | Define the duplicate-email test, including normalization before the duplicate lookup. |
| 121 | `    response = api.client.post("/api/auth/register", json={` | Try to register another account using the existing citizen email in a different presentation. |
| 122 | `        "full_name": "Duplicate Citizen", "email": " CITIZEN@EXAMPLE.COM ",` | Supply a new name with uppercase, padded existing email. |
| 123 | `        "password": TEST_PASSWORD,` | Supply a valid password so duplication, rather than password validation, is the intended rejection. |
| 124 | `    })` | Finish the duplicate registration call. |
| 125 | `    assert response.status_code == 409` | Require HTTP 409 Conflict for an email that is already registered. |
| 126 | `    with api.sessions() as db:` | Open a direct database session to check that rejection left the existing data intact. |
| 127 | `        assert len(list(db.scalars(select(User).where(User.email == "citizen@example.com")))) == 1` | Select all rows with the normalized citizen email and require exactly one; this checks no duplicate account was inserted. |
| 130 | `@pytest.mark.parametrize("privilege", [{"role": "admin"}, {"role": "response_team"}, {"team_id": 1}])` | Parametrize privilege over three JSON fragments: attempted admin role, attempted response_team role, and attempted team assignment. Pytest creates three separate cases. |
| 131 | `def test_public_registration_rejects_privilege_fields(api, privilege):` | Define the public-registration privilege test; privilege receives one fragment per case and api is newly created for each. |
| 132 | `    response = api.client.post("/api/auth/register", json={` | Start registration of a new synthetic attempted account. |
| 133 | `        "full_name": "Escalation Attempt", "email": "attempt@example.com",` | Supply an otherwise valid name and email. |
| 134 | `        "password": TEST_PASSWORD, **privilege,` | Provide a valid password and unpack privilege into the JSON dictionary with **. This inserts the forbidden field being tested. |
| 135 | `    })` | Finish the request. |
| 136 | `    assert response.status_code == 422` | Require HTTP 422 validation rejection because RegisterRequest forbids extra fields such as role and team_id. |
| 137 | `    with api.sessions() as db:` | Open the test database to check that schema rejection had no account-creation effect. |
| 138 | `        assert db.scalar(select(User).where(User.email == "attempt@example.com")) is None` | Require no User row for the attempted email; an HTTP error alone would not prove that no row was created. |
| 141 | `@pytest.mark.parametrize("change", [` | Start a parametrization list of invalid input changes, creating four independent cases. |
| 142 | `    {"full_name": " " * 10}, {"email": "invalid-email"},` | Define invalid-name and invalid-email cases: ten spaces become an empty normalized name, and invalid-email fails email-format validation. |
| 143 | `    {"password": "short"}, {"password": 1234567890},` | Define a password shorter than ten characters and an integer password. StrictStr rejects the integer rather than coercing it to text. |
| 144 | `])` | Close the four-case parametrization decorator. |
| 145 | `def test_invalid_registration_creates_no_account(api, change):` | Define the invalid-registration test; change is the selected invalid field replacement. |
| 146 | `    response = api.client.post("/api/auth/register", json={` | Begin an otherwise valid registration request. |
| 147 | `        "full_name": "Invalid Citizen", "email": "invalid@example.com",` | Supply a valid baseline name and email. |
| 148 | `        "password": TEST_PASSWORD, **change,` | Supply a valid baseline password, then unpack change last so its invalid value replaces the matching baseline field. |
| 149 | `    })` | Finish the request. |
| 150 | `    assert response.status_code == 422` | Require HTTP 422 for each invalid body. |
| 151 | `    with api.sessions() as db:` | Open a direct ORM session after validation rejection. |
| 152 | `        assert len(list(db.scalars(select(User)))) == 3` | Require exactly the three fixture users to remain; no fourth account should have been created. |
| 155 | `def test_password_whitespace_remains_significant(api):` | Define the password-whitespace test, distinguishing password characters from normalized name/email whitespace. |
| 156 | `    password = f"  {TEST_PASSWORD}  "` | Create a password containing two additional spaces before and after the synthetic password. |
| 157 | `    response = api.client.post("/api/auth/register", json={` | Register a new account using the padded password. |
| 158 | `        "full_name": "Whitespace Citizen", "email": "spaces@example.com", "password": password,` | Supply valid account details and preserve the exact padded password in the JSON body. |
| 159 | `    })` | Finish registration. |
| 160 | `    assert response.status_code == 201` | Require successful account creation with those spaces included in the password. |
| 161 | `    assert api.client.post("/api/auth/login", json={` | Begin a login attempt that deliberately omits the spaces from the password. |
| 162 | `        "email": "spaces@example.com", "password": TEST_PASSWORD,` | Send the same email but the unpadded synthetic password. |
| 163 | `    }).status_code == 401` | Finish login and require HTTP 401 because the unpadded password differs from the stored one. |
| 164 | `    assert api.client.post("/api/auth/login", json={` | Begin a second login using the exact password that was registered. |
| 165 | `        "email": "spaces@example.com", "password": password,` | Send the original padded password, preserving every space. |
| 166 | `    }).status_code == 200` | Finish login and require HTTP 200. Together, these checks demonstrate the schema/service do not silently trim passwords. |
| 169 | `def test_correct_login_normalizes_email(api):` | Define the successful-login normalization test for an existing seeded account. |
| 170 | `    response = api.client.post("/api/auth/login", json={` | Begin a login POST. |
| 171 | `        "email": " CITIZEN@EXAMPLE.COM ", "password": TEST_PASSWORD,` | Send uppercase and padded citizen email together with the correct password. |
| 172 | `    })` | Finish the request. |
| 173 | `    assert response.status_code == 200` | Require HTTP 200 for the normalized existing email. |
| 174 | `    assert response.json()["token_type"] == "bearer"` | Require token_type to be bearer, matching how the client must use access_token. |
| 175 | `    assert response.json()["user"]["role"] == "citizen"` | Require the response user to report the citizen role. |
| 178 | `@pytest.mark.parametrize("email,password", [` | Parametrize pairs of email and password to test two distinct authentication failures. |
| 179 | `    ("citizen@example.com", "Incorrect-password!2026"),` | Define a real account with an incorrect, otherwise valid-length password. |
| 180 | `    ("missing@example.com", TEST_PASSWORD),` | Define a nonexistent account with the shared valid-length test password. |
| 181 | `])` | Close the two-case parameter list. |
| 182 | `def test_invalid_login_rejected_without_creating_session(api, email, password):` | Define the invalid-login test, taking the supplied email/password pair and a fresh database harness. |
| 183 | `    response = api.client.post("/api/auth/login", json={"email": email, "password": password})` | Send the selected invalid credentials to the login route. |
| 184 | `    assert response.status_code == 401` | Require HTTP 401 Unauthorized for both an incorrect password and an unknown account. |
| 185 | `    assert response.headers["WWW-Authenticate"] == "Bearer"` | Require the Bearer authentication challenge header on the failed response. |
| 186 | `    with api.sessions() as db:` | Open a database session after the unsuccessful login. |
| 187 | `        assert list(db.scalars(select(TokenSession))) == []` | Require no TokenSession rows, showing failed authentication did not create a usable or orphaned session. |
| 190 | `def test_logout_revokes_only_the_current_session(api):` | Define the logout test that distinguishes one user's two independent sessions. |
| 191 | `    first = {"Authorization": f"Bearer {api.login('citizen')['access_token']}"}` | Log in once and build Authorization headers for the first session. |
| 192 | `    second = {"Authorization": f"Bearer {api.login('citizen')['access_token']}"}` | Log in again and build headers for a second session; using login directly avoids the Harness token cache and creates another persisted session. |
| 193 | `    assert api.client.post("/api/auth/logout", headers=first).status_code == 204` | Log out the first session and require HTTP 204 No Content. |
| 194 | `    assert api.client.get("/api/users/me", headers=first).status_code == 401` | Require the revoked first token to fail on /api/users/me with HTTP 401. |
| 195 | `    assert api.client.post("/api/auth/logout", headers=first).status_code == 401` | Require another logout with the already revoked first token to fail authentication with HTTP 401. |
| 196 | `    assert api.client.get("/api/users/me", headers=second).status_code == 200` | Require the independently created second token to remain valid with HTTP 200. |
| 197 | `    with api.sessions() as db:` | Open the database to inspect both persisted session records. |
| 198 | `        sessions = list(db.scalars(select(TokenSession).where(TokenSession.user_id == api.users["citizen"])))` | Select every session owned by the seeded citizen account. |
| 199 | `        assert len(sessions) == 2` | Require two rows to remain; logout marks a session revoked instead of deleting it. |
| 200 | `        assert sum(session.revoked_at is not None for session in sessions) == 1` | Count non-null revoked_at values and require exactly one. In Python, True counts as one and False as zero in sum. |
| 203 | `def test_expired_persisted_session_rejects_token(api):` | Define the test of an expired database session while the client still holds its original token. |
| 204 | `    headers = api.headers("citizen")` | Log in through the header helper, creating and caching a valid citizen session. |
| 205 | `    with api.sessions() as db:` | Open a direct ORM session to alter that persisted session. |
| 206 | `        session = db.scalar(select(TokenSession).where(TokenSession.user_id == api.users["citizen"]))` | Select the citizen's TokenSession row. |
| 207 | `        session.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)` | Set the database expiry to one minute before the current UTC time. This changes the database row only, not the encoded JWT's exp claim. |
| 208 | `        db.commit()` | Commit the changed expiry. |
| 209 | `    assert api.client.get("/api/users/me", headers=headers).status_code == 401` | Require the still-held bearer token to be rejected with HTTP 401, demonstrating a database expiry check independent of JWT verification. |
| 212 | `def test_deleted_persisted_session_rejects_token(api):` | Define the test of a token whose database session has been removed. |
| 213 | `    headers = api.headers("citizen")` | Obtain authorization headers from a valid citizen login. |
| 214 | `    with api.sessions() as db:` | Open the database for direct manipulation. |
| 215 | `        session = db.scalar(select(TokenSession).where(TokenSession.user_id == api.users["citizen"]))` | Select the citizen's session row. |
| 216 | `        db.delete(session)` | Stage deletion of that session from the database. |
| 217 | `        db.commit()` | Commit deletion. |
| 218 | `    assert api.client.get("/api/users/me", headers=headers).status_code == 401` | Require the token to fail with HTTP 401 because a signed token must also reference an existing persisted session. |
| 221 | `def test_inactive_account_rejects_existing_token_and_new_login(api):` | Define the test that disabling an account blocks both an existing session and a new login. |
| 222 | `    headers = api.headers("citizen")` | Log in while the seeded citizen is still active and save its token headers. |
| 223 | `    with api.sessions() as db:` | Open a database session to change account state. |
| 224 | `        db.get(User, api.users["citizen"]).active = False` | Load the citizen by primary-key ID and set active to False. |
| 225 | `        db.commit()` | Commit the account's inactive state. |
| 226 | `    assert api.client.get("/api/users/me", headers=headers).status_code == 401` | Require the previously valid token to fail on /api/users/me, showing activity is checked against the current database record. |
| 227 | `    assert api.client.post("/api/auth/login", json={` | Begin a fresh login attempt for the disabled user. |
| 228 | `        "email": "citizen@example.com", "password": TEST_PASSWORD,` | Supply the disabled account's correct credentials. |
| 229 | `    }).status_code == 401` | Finish the request and require HTTP 401; correct credentials do not bypass active=False. |
| 232 | `@pytest.mark.parametrize("path", ["/api/users/me", *WORKSPACES.values()])` | Parametrize four protected GET routes: /api/users/me plus the three workspace URLs. The star expands the mapping's values into the list. |
| 233 | `def test_protected_routes_reject_missing_and_invalid_authentication(api, path):` | Define the missing/invalid authentication test for each selected route. |
| 234 | `    assert api.client.get(path).status_code == 401` | Call the route without Authorization and require HTTP 401. |
| 235 | `    assert api.client.get(path, headers={"Authorization": "Bearer invalid-token"}).status_code == 401` | Call the route with a malformed token string and require HTTP 401. This checks invalid-token rejection, not every validly encoded JWT failure mode. |
| 238 | `def test_logout_requires_authentication(api):` | Define the separate authentication requirement test for the POST logout route. |
| 239 | `    assert api.client.post("/api/auth/logout").status_code == 401` | POST logout without a bearer header and require HTTP 401. |
| 242 | `@pytest.mark.parametrize("role", list(WORKSPACES))` | Parametrize the three role keys from WORKSPACES; each role receives its own fresh harness. |
| 243 | `def test_roles_can_enter_only_their_own_workspace(api, role):` | Define the role-access matrix test for one signed-in role at a time. |
| 244 | `    headers = api.headers(role)` | Get a valid bearer token for the selected seeded role. |
| 245 | `    account = api.client.get("/api/users/me", headers=headers)` | Call /api/users/me with the authenticated headers. |
| 246 | `    assert account.status_code == 200` | Require successful current-account retrieval. |
| 247 | `    assert account.json()["role"] == role` | Require the returned role to match the account used for login. |
| 248 | `    assert "password_hash" not in account.json()` | Require the current-user JSON to exclude the stored password_hash field. |
| 249 | `    for workspace_role, path in WORKSPACES.items():` | Iterate through all three workspace role/URL pairs; across the three parametrized cases this checks all nine role-to-workspace combinations. |
| 250 | `        response = api.client.get(path, headers=headers)` | Call the selected workspace with the current role's bearer token. |
| 251 | `        assert response.status_code == (200 if workspace_role == role else 403)` | Require 200 only for the matching role and 403 for either different role. In this implementation admins have no implicit access to citizen or response-team workspaces. |
| 252 | `        if workspace_role == role:` | If this is the allowed workspace, inspect its success JSON too. |
| 253 | `            assert response.json()["role"] == role` | Require the workspace response's role field to match the authorized role. |
| 254 | `            assert response.json()["title"]` | Require title to be truthy, meaning present and nonempty; this does not assert an exact title string. |
| 255 | `            assert response.json()["message"]` | Require message to be truthy, meaning present and nonempty; the route remains a permission demonstration rather than an incident-management workflow. |
| 258 | `def test_role_changes_take_effect_for_an_existing_session(api):` | Define the test of a database role change while an existing token remains in use. |
| 259 | `    headers = api.headers("citizen")` | Obtain citizen authorization headers once; the same session is used before and after the role change. |
| 260 | `    assert api.client.get(WORKSPACES["citizen"], headers=headers).status_code == 200` | Require the initial citizen-workspace request to succeed. |
| 261 | `    with api.sessions() as db:` | Open a database session to modify the account directly. |
| 262 | `        db.get(User, api.users["citizen"]).role = Role.ADMIN` | Load the seeded citizen account and change its stored role to Role.ADMIN. |
| 263 | `        db.commit()` | Commit the role change. |
| 264 | `    assert api.client.get(WORKSPACES["citizen"], headers=headers).status_code == 403` | Require the same token to lose citizen-workspace access with HTTP 403. |
| 265 | `    assert api.client.get(WORKSPACES["admin"], headers=headers).status_code == 200` | Require the same token to gain admin-workspace access with HTTP 200. This demonstrates current DB role checks, rather than embedding a fixed authorization role in the JWT. |
| 268 | `def test_health_checks_database_connection(api):` | Define the successful health-check test using the fixture database. |
| 269 | `    response = api.client.get("/health")` | Request the public /health route. |
| 270 | `    assert response.status_code == 200` | Require HTTP 200 while the test database is available. |
| 271 | `    assert response.json()["status"] == "ok"` | Require the returned overall status to be ok. |
| 272 | `    assert response.json()["database"] == "connected"` | Require database to report connected, consistent with /health executing SELECT 1. This case does not simulate an unavailable database. |

## Source-verification record

Checked on **6 October 2026** against the local source: **41 files, 1581 physical source lines, and 1359 nonblank lines explained individually**. The remaining 222 lines are blank readability separators. A structural check verified that each file's table contains exactly its nonblank source line numbers, in order, with no duplicates or omissions, and that every reproduced code cell matches its source text with outer display whitespace ignored.

Markdown parsing also verified 41 complete source tables with 1359 explanation rows and three columns per row. The guide includes three Mermaid diagram blocks. Independent reviews checked the overview, frontend behavior, and supporting descriptions against the source.

Pytest collection in the existing parent Python environment confirmed **27 cases**. A full test execution was attempted but did not return a completed result and was stopped; this explanation therefore does not claim a fresh passing API test run. The README's earlier verification report is historical project documentation. No new browser, production build, PostgreSQL deployment, or accessibility audit was performed for this documentation task.

The installed pwdlib implementation was inspected to confirm that PasswordHash.recommended selects Argon2. No application source was changed while preparing this guide.
