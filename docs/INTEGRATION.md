# Week 1 integration record

## Source branches

Repository: <https://github.com/Athulanisoya/ResQ-Kerala>

The local integration branch is `complete-week1-htmx`. The four supplied branch heads were fetched and preserved in Git history:

| Member / branch | Source commit | Contribution present in the source |
| --- | --- | --- |
| Arya / `arya` | `19fa069ee3da232faad82376bd88c7c18d61fd3f` | Incident creation/read/history, validation and report models |
| Athul / `athul-week1` | `69387831874d1902cf1ef497b846fd7a7daf918c` | Account registration/login/logout, JWT sessions, password hashing and role permissions |
| Vidya / `vidya-week1` | `129165986bfecf7ad2ce23ad2342f74e65210177` | Report creation/status backend, disaster type and status endpoints |
| Maanaz / `week1-maanaz` | `19fa069ee3da232faad82376bd88c7c18d61fd3f` | Same source commit as `arya`; no separate admin-review or team-assignment implementation existed at this head |

Merge commits `3d279f3` and `88b9ebe` preserve the authentication and reporting branch ancestry. Arya and Maanaz point to the same commit, so merging that shared ancestor does not produce an additional distinct merge commit. No remote push or publication is part of this local delivery.

## Accepted scope

The supplied `ResQ_Kerala_Complete_Project_Discussion.md`, section 25, defines Week 1 as registration, login, citizen reporting, admin review, team assignment and status tracking. The supplied `ResQ_Kerala_Member_Weekly_Guide.pptx`, slides 4–8, assigns authentication to Athul, incident APIs/validation to Arya, admin review/assignment to Maanaz, and citizen forms/status to Vidya.

The guide's slide 2 explains that its file references are cumulative final targets rather than saved weekly builds. Later-week modules are therefore not acceptance requirements for this delivery. The user's current HTMX requirement replaces the plans' React frontend examples.

The complete Week 1 flow is:

```text
Citizen account → flood report → admin review → verification
→ available response team assignment → citizen/team status views
```

Statuses stop at `ASSIGNED` (displayed as **Team assigned**). Rescue execution, relief distribution, shelter management, chatbot, AI models/agents, alerts, notifications, translation, clarification and closure are excluded.

## Necessary backend integration

The source branches could not be combined into a working application unchanged. The fixes are limited to shared contracts, runtime compatibility and the explicitly required Week 1 workflow:

- Use the authentication branch's SQLAlchemy base, database sessions and JWT identity consistently. Separate model metadata would otherwise create incomplete or conflicting tables, while the incident branch's caller-supplied user ID did not connect to authenticated accounts.
- Register the combined user, session, incident, history and team models with the shared database metadata and load the combined routers at startup.
- Reconcile incident fields, including `disaster_type`, and the report/status response contracts so the member APIs agree.
- Connect citizen ownership and role checks to the authentication principal. Retain the report reference and history behavior from the reporting work.
- Save initial report/history rows in one transaction and replace the original count-derived report reference with a unique UUID-based reference; concurrent submissions could otherwise reuse a reference. Keep the authentication branch's account/password/JWT implementation intact.
- Restrict the supplied status-update endpoint to the Week 1 review states and permitted admin actions, preserving a coherent saved timeline.
- Supply the missing admin queue/review and available-team assignment behavior. The Maanaz branch head contained no distinct implementation of these required tasks. Persist assignment, availability and status/history changes together, and expose assigned reports to the appropriate team.
- Seed local demonstration accounts and a usable response team for the required three-role demonstration.

These changes enable the specified basic workflow; they do not add the later disaster-response modules. For review, compare the final backend files against the source commits above and inspect the integration diff rather than assuming every member supplied a complete module.

## HTMX frontend

The UI adapter is `web/app.py`, served by `uvicorn web.app:app` on `127.0.0.1:8013`. Templates and static assets live in `frontend/templates/` and `frontend/static/`. Server-rendered templates and HTMX requests provide registration/login, citizen reports and timeline, the admin review/assignment workspace and team assignments. Backend JSON routes remain reachable under their existing `/api/...` paths, with `/docs` and `/openapi.json` on the same host.

The original React source remains available in the source branch history. Its active files were replaced by the HTMX frontend. There is one application process and no Node.js requirement for the delivered UI.

HTMX **2.0.11** is vendored at `frontend/static/vendor/htmx.min.js` from the official npm distribution (`https://cdn.jsdelivr.net/npm/htmx.org@2.0.11/dist/htmx.min.js`). Its verified SHA-384 integrity value is `sha384-2OatzQy1H+Zd/IIrjr1TcuDGqLXeHhbooAyJY1KdQMKnr4LZ22k31GBLdYKHmVjg`. The upstream license is included at `frontend/static/vendor/HTMX-LICENSE.txt`. Serving this file locally removes the UI's dependency on a live CDN connection.

## Local configuration and verification

`scripts/setup.ps1` creates or reuses this workspace's Python environment, installs pinned dependencies, initializes its own PostgreSQL 18 cluster at `.runtime/postgres` and seeds the demonstration accounts. Database and schema are `resq_week1`; the local user is `resq_local`; PostgreSQL listens on `127.0.0.1:5443`. Settings and generated passwords remain in ignored local files. Repeated setup preserves the existing cluster, signing secret, accounts and reports.

`scripts/start.ps1` starts/reuses the isolated database and application. The application record includes PID and process creation time. `scripts/stop.ps1` checks that identity and the workspace command line before stopping the recorded application, then stops this workspace's PostgreSQL data directory. It does not use a machine-wide PostgreSQL service or stop other ResQ projects.

Run the automated tests, read-only readiness command and browser demonstration from the README. Required acceptance includes citizen ownership, invalid report rejection, authenticated role boundaries, admin review, available-team assignment, persistence and status/history visibility. Passing static checks or a health endpoint alone does not establish that the browser workflow works. Verification results belong to the delivery report and local test evidence; this document does not claim checks that have not been run.
