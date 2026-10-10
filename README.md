# Athul — Week 1

This folder contains **only Athul's first-week work** from slide 5 of `ResQ_Kerala_Member_Weekly_Guide.pptx`: registration, login, logout, password hashing, JWT authentication, and role permissions. It is a small runnable authentication module, extracted from the shared Week 1 project.

## Included files

| Athul's responsibility | Implementation |
| --- | --- |
| Register, login and logout endpoints | `backend/routers/auth.py` |
| Account responses and sessions | `backend/services/auth_service.py` |
| Register/login validation | `backend/schemas/auth.py`, `auth_schema.py` |
| Password hashing | `backend/utils/security.py` |
| JWT creation and validation | `backend/utils/jwt.py` |
| Authenticated-user and role checks | `backend/utils/permissions.py` |
| Registration/login screens | `frontend/src/components/shared/Login.jsx` |
| Session and role navigation | `frontend/src/App.jsx` |

The minimal account model, persisted session table, database connection, API client, app entry points, seed data, scripts, focused tests, and role workspace endpoints support these tasks. There are no incident, reporting, assignment, rescue, relief, shelter, chatbot, or AI modules in this folder.

## Run

Use PowerShell 7 from the **Athul** directory. Requirements: Python 3.11+, Node.js 22.12+ or supported newer Node, and a running PostgreSQL instance.

```powershell
.\scripts\setup.ps1
.\scripts\start.ps1
```

If the parent project is configured, setup reuses its PostgreSQL connection and generates a **new** signing secret. Authentication data is isolated in the **`athul_week1` schema**, with only `users` and `token_sessions` tables. It does not copy the parent's accounts, passwords, reports, or operational data. The PostgreSQL server must be running; this module does not own or stop the shared database service.

If this folder is used elsewhere, copy `.env.example` to `.env`, configure your existing PostgreSQL database and a random signing secret, then run setup. The database account needs permission to create the `athul_week1` schema.

For development in this workspace, `setup.ps1 -SkipInstall` can reuse the parent's installed Python environment; frontend dependencies must already be installed in this folder. A normal setup creates its own `.venv` and runs `npm ci`.

- UI: <http://127.0.0.1:5175>
- API docs: <http://127.0.0.1:8012/docs>
- Local demo accounts: **`.runtime/demo-accounts.json`**, generated privately by setup.
- Stop only this module: `.\scripts\stop.ps1`.

The parent full application remains available on its own ports, 5174 and 8011.

## Athul's demonstration

1. Register a citizen, sign in, and open **Citizen workspace** and **My account**.
2. Sign out and sign in as the locally provisioned admin, then open **Admin workspace**.
3. Sign in as the response-team account and open **Response team workspace**.
4. Show the access-check table: the role's own endpoint succeeds and the other role endpoints return `403`. Anonymous access returns `401`.
5. Sign out. The saved session is revoked immediately, so its former token can no longer access protected endpoints.

Public registration always creates a citizen. Admin and response-team accounts are provisioned locally; there is no privileged role selector during registration. Workspace pages demonstrate real authentication and role checks and contain no other member's operational features.

## Test and build

```powershell
.\.venv\Scripts\python.exe -m pytest
Push-Location frontend
npm.cmd run build
Pop-Location
```

When reusing the parent environment, run `..\.venv\Scripts\python.exe -m pytest` from here instead. Tests use an isolated in-memory SQLite database; the runnable module uses PostgreSQL.

See `docs/week1-tasks.md` for task ownership and integration notes. This extraction preserves the shared auth API contract. When integrating into the full application, use the full project's account/team models and routers rather than replacing them with this demonstration's minimal model.

For the complete working, feature overview, request flows, and line-by-line explanations of all source/configuration files, see [the code explanation guide](docs/CODE_EXPLANATION.md).

Secrets, local credentials, dependencies, logs, and generated build output are ignored by Git. Keep `.env` and `.runtime` private. This is a local Week 1 demonstration; it does not contact disaster or emergency services.

Verified on 6 October 2026: **27 auth tests passed**, the production frontend build passed, and Chrome checks passed for registration, login/logout, all three role permissions, account details, reload/session restoration, token revocation, and mobile rendering. The local PostgreSQL setup created only `athul_week1.users` and `athul_week1.token_sessions`. The module's start/reuse/stop/restart scripts also passed. Private browser evidence is in `.runtime/verification.json` and the mobile screenshots in `.runtime`.
