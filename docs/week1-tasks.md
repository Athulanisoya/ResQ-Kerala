# ResQ — historical Week 1 authentication tasks

This note records the original independent ResQ Week 1 authentication contribution: **registration, login, logout, and role permissions**. That contribution had its own backend and React frontend for independent development and demonstration.

**Historical snapshot:** paths, ports and feature limits below describe the original authentication subset. Example identifiers have been adapted to the current ResQ naming. The current workspace combines all four contributions and uses HTMX; use the [current README](../README.md) and [integration record](INTEGRATION.md) for its complete workflow and setup.

The authentication assignment comes from slide 5 of the supplied `ResQ_Kerala_Member_Weekly_Guide.pptx`. The slide's demo is: register, sign in as each role, show allowed pages, and sign out. The broader architecture and Week 1 scope come from sections 20 and 25 of the supplied `ResQ_Kerala_Complete_Project_Discussion.md`. The weekly guide determines this contribution's ownership where the longer discussion describes different divisions.

## Assigned files

All paths below are relative to `<authentication-source-root>`, the original standalone contribution.

| Guide path | Authentication responsibility |
| --- | --- |
| `backend/routers/auth.py` | Register, login, and logout endpoints. |
| `backend/services/auth_service.py` | Create citizen accounts, verify credentials, create authenticated account responses, and revoke the current session. |
| `backend/schemas/auth_schema.py` | Public import path for validated registration/login input and account/token responses. The schema definitions live in `backend/schemas/auth.py`. |
| `backend/utils/security.py` | Hash passwords and verify their hashes. |
| `backend/utils/jwt.py` | Issue and validate signed session tokens. |
| `backend/utils/permissions.py` | Resolve the authenticated account/session and enforce allowed roles at the API. This is a shared file in the complete project. |
| `frontend/src/components/shared/Login.jsx` | Registration/login forms and validation feedback. |
| `frontend/src/App.jsx` | Session handling, logout, and role-specific navigation. This is a shared file in the complete project. |

The independent demonstration needs a small amount of supporting code: settings, database connection, `User` and `TokenSession` models, current-account and role-workspace routes, application startup, local account seeding, frontend API calls/styles, and setup/run scripts. These support authentication; they do not add the other members' business modules.

## Completed behavior to demonstrate

1. Register a citizen with a name, email, and password. Registration also signs the citizen in.
2. Sign out and sign in again. Duplicate emails are rejected after case/whitespace normalization. Password whitespace remains significant.
3. Sign in with each local demonstration account: `citizen`, `admin`, and `response_team`.
4. Open the workspace allowed for that account. The API enforces the role even if somebody calls another workspace endpoint directly.
5. Sign out. The saved session is revoked immediately, and its token no longer opens protected endpoints. A separate login session remains valid.

Public registration always creates a **citizen**. It rejects submitted privilege fields such as `role` and `team_id`. Admin and response-team accounts are provisioned through the local seed script, with sign-in details stored in an ignored local runtime file.

The three workspace screens are permission demonstrations. They have no business operations. This folder ends at authentication and role navigation.

## API handoff

| Method | Endpoint | Access / response |
| --- | --- | --- |
| `POST` | `/api/auth/register` | Public. Accepts `full_name`, `email`, `password`; returns a token and citizen account with `201`. |
| `POST` | `/api/auth/login` | Public. Accepts `email`, `password`; returns a token and account. |
| `POST` | `/api/auth/logout` | Signed-in account; revokes the supplied session and returns `204`. |
| `GET` | `/api/users/me` | Signed-in account; returns its public account details. |
| `GET` | `/api/workspaces/citizen` | Citizen role only. |
| `GET` | `/api/workspaces/admin` | Admin role only. |
| `GET` | `/api/workspaces/response-team` | Response-team role only. |
| `GET` | `/health` | Public database-connection check. |

Protected requests send `Authorization: Bearer <access_token>`. Successful login/registration responses contain `access_token`, `token_type: "bearer"`, and `user`. Passwords and hashes never appear in account responses. Role workspace responses contain `role`, `title`, and `message`. Missing, invalid, expired, revoked, or inactive-account authentication returns `401`; a signed-in account with the wrong role receives `403`.

Passwords use Argon2 hashes. Each JWT refers to a saved `TokenSession`, so logout is checked by the backend as well as the frontend. Role checks read the account's current role from the database. The frontend stores the active session per browser tab and clears it after logout or an expired-session response.

## Data and setup

PostgreSQL stores this demonstration's two tables, `users` and `token_sessions`, in the separate `resq_week1` schema. Its account/session records are independent of the full Week 1 application's records, even when setup reuses the same local PostgreSQL service. `team_id` is an optional account field retained for the shared response contract; this subset does not provision or manage teams.

The standalone contribution used its own environment configuration, JWT secret, and separate API/browser ports. Local credential and runtime files were ignored. The [current README](../README.md) now provides setup and run commands for the integrated application.

## Verification

`backend/tests/test_auth.py` uses a fresh in-memory SQLite database with the explicit test-only setting. It exercises registration validation, hashing, duplicate emails, rejected privilege fields, significant password whitespace, correct/incorrect login, current-account access, logout revocation, expiry, missing sessions, inactive accounts, and the three-role permission matrix. It also checks that database role changes affect existing sessions.

These isolated API tests do not establish PostgreSQL deployment or browser behavior; see [the current validation record](VALIDATION.md) for the checks performed on the integrated application.

## Integration into the full project

Use the authentication API contract and utility functions when integrating this contribution. Coordinate edits to `permissions.py` and `App.jsx`, which the weekly guide marks as shared. Keep the full project's business screens and route composition when merging the authentication shell; this standalone shell only includes permission-demo workspaces.

The standalone PostgreSQL schema and configuration are for independent development. A full-project integration should use the full project's account models, database configuration, and session secret. Preserve the public citizen-only registration rule, server-side role gates, and logout revocation behavior.
