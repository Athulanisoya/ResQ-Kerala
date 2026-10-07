# ResQ Kerala local setup

This checkout provides a FastAPI incident-reporting backend. Its interactive API
documentation is at <http://127.0.0.1:8000/docs>; there is no separate frontend here.

From the project folder in PowerShell:

```powershell
.\scripts\start.ps1
.\scripts\stop.ps1
```

The start command runs the API and its project database in the background.
PostgreSQL 18 is installed at `C:\Program Files\PostgreSQL\18`. This project uses
its own database on `127.0.0.1:5442`, with data in `.runtime/postgres`; the existing
PostgreSQL server on port 5432 keeps its own configuration.

The `.env` file configures the database connection and references
`.runtime/pgpass.conf` for the password. Keep that password file and database data
local. API and database logs are in `.runtime/api.log` and `.runtime/postgres.log`.
The Python 3.11 environment in `.venv` has been repaired for this computer.

For incident endpoints, provide a positive integer in the `X-User-Id` header.
In Swagger, expand an endpoint, select **Try it out**, and enter that value.

Verification:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests -q
.\.venv\Scripts\python.exe -m scripts.verify_local
```

The live check creates and removes its own temporary incident, verifying the
database connection, submission, retrieval, status history, and ownership checks.
