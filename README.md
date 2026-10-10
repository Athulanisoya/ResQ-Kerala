# ResQ Kerala — complete Week 1

This version combines the four member branches into one flood reporting application with an HTMX frontend. Citizens register, sign in, submit reports and view their status. Administrators review and verify reports, then assign an available response team. Response teams can view their assigned reports. The timeline ends at **Team assigned** for Week 1.

## Run on this computer

From this project directory in PowerShell:

```powershell
.\scripts\setup.ps1 -PythonCommand python
.\scripts\start.ps1
```

Open [the application](http://127.0.0.1:8013) or [API documentation](http://127.0.0.1:8013/docs). Setup creates a fresh `.venv` if needed, installs `requirements.txt`, initializes this workspace's PostgreSQL cluster and provisions the demo accounts. HTMX and CSS are served by the same Python application; Node.js and a separate frontend server are unnecessary.

Requirements: Windows, Python 3.11+, and PostgreSQL 18 binaries at `C:\Program Files\PostgreSQL\18\bin`. Python must be available on PATH, or pass its executable path with `-PythonCommand`. If dependencies are already installed, rerun `.\scripts\setup.ps1 -SkipInstall`.

The database listens only on `127.0.0.1:5443`, uses database/schema `resq_week1`, and stores its files in `.runtime/postgres`. This isolates it from the other ResQ checkouts. Both ports, **5443** and **8013**, must be available. Setup preserves generated credentials and existing records on subsequent runs.

## Demo accounts

Setup writes the generated password and three account details to the ignored, local **`.runtime/demo-accounts.json`** file. Open that file locally to sign in as `citizen@resq.example.com`, `admin@resq.example.com`, or `team@resq.example.com`. Public registration creates citizens only. Admin and team roles are provisioned by setup.

Keep `.env`, `.runtime`, and `.venv` private and outside commits. `.runtime/pgpass.conf` contains the database password; `.env` contains the signing secret and the connection configuration.

## Week 1 demonstration

1. Register a citizen, sign in and submit a flood report with its location, people affected and help required.
2. Open **My Reports** and the report detail/status timeline.
3. Sign out, sign in as the admin, open the report queue and move the report through review and verification.
4. Assign an available response team. Check that the report shows **Team assigned**.
5. Sign in as the team to view its assignment, then as the citizen to view the updated timeline.

AI analysis, alerts, rescue progress, relief, shelters, chatbot, notifications, Malayalam translation and case closure remain later-week work.

## Stop and verify

```powershell
.\scripts\stop.ps1
```

Stop checks the recorded application's PID, creation time and command line before terminating it, and shuts down only `.runtime/postgres` belonging to this workspace. Start reuses this workspace's existing application when it is already running.

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m scripts.verify_local
```

The readiness command requires the application to be running and checks PostgreSQL, the home page, API docs and the authentication gate without creating a report. Tests use an isolated test database. Browser demonstration is a separate check from automated tests.

API paths include `/api/auth/register`, `/api/auth/login`, `/api/auth/logout`, `/api/users/me`, `/api/incidents/`, report detail/history/status, the admin report queue/assignment actions, and `/api/teams/assignments`. Consult the running API docs for exact methods and request bodies. Protected JSON APIs require the bearer token returned by login.

If setup fails, confirm the PostgreSQL binary path and port availability. If startup fails, check `.runtime/postgres.log`, `.runtime/web.log` and `.runtime/web-error.log`. Do not replace the generated database password while retaining an existing cluster. If PowerShell's script policy blocks a command, run it explicitly with `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup.ps1` and then the corresponding `start.ps1` command.

See [integration notes](docs/INTEGRATION.md) for branch provenance, Week 1 boundaries and the necessary backend compatibility changes, and [validation results](docs/VALIDATION.md) for the completed checks. Original React files are preserved in the source branch history; the active frontend uses HTMX templates and static assets. Older member-specific documents describe their original branches and should be read in that context.
