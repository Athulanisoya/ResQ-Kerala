# ResQ Kerala — integrated Week 2

This integration combines `athul-week2`, `Vidya-week2`, `aryaweek2`, and `week2-maanaz` in one PostgreSQL-backed FastAPI/HTMX application. It retains citizen reporting, per-tab login, administrator review and team assignment, and adds Kerala location extraction, scheduled alerts and alert matching, the trained severity classifier, reviewed analysis, and investigation assignment/findings/completion.

Each submitted report receives a sourced Kerala geography check and a saved local summary draft. On the admin report detail page, **Analyze location** checks current alerts, **Predict severity** runs Vidya's bundled classifier, and **Save assessment** records the reviewed severity, location, alert match, summary and investigation decision. Older reports expose **Generate summary**, and **Refresh summary** updates the generated draft without changing a reviewed assessment. Investigators can be assigned and their findings updated or completed. The original citizen report and its status/team workflow are preserved.

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

### Sign-in, account and permissions

Each tab keeps its bearer session in `sessionStorage`, so citizens, administrators and response teams can sign in independently in separate tabs of the same browser. Reloads, direct links and history navigation revalidate that tab's session with the server. JavaScript is required. Tabs opened by duplicating an existing tab may initially inherit its session; sign out and sign in independently when demonstrating different accounts. The previous shared authentication cookie is ignored and removed, so existing cookie-based sign-ins require one fresh login after this update.

**My account** shows the authenticated name, email, role, user ID and optional team ID. **Workspace permissions** checks all three protected role endpoints and displays their actual allowed/denied results, with a button to check again.

Expired sessions show a sign-in notice. Temporary service failures keep the saved tab session and offer **Try again** or **Sign in again**. Signing out revokes only that server session; if revocation cannot be confirmed, the app clears this tab's sign-in and explains that the previous server session may remain valid until expiry.

User team memberships reference `response_teams.id` with a database foreign key. Startup adds this constraint to existing valid PostgreSQL tables without changing account data. If existing accounts reference missing teams, startup stops with an explanation and preserves those records for correction.

## Week 1 demonstration

1. Register a citizen, sign in and submit a flood report with its location, people affected and help required.
2. Open **My Reports** and the report detail/status timeline.
3. Sign out, sign in as the admin, open the report queue and move the report through review and verification.
4. Assign an available response team. Check that the report shows **Team assigned**.
5. Sign in as the team to view its assignment, then as the citizen to view the updated timeline.

## Week 2 demonstration

1. Sign in as admin and open **Official alerts**. Create an active demo alert for Alappuzha district, or choose another recognised Kerala place. Alert form times use IST.
2. In a separate citizen tab, submit a clearly labelled synthetic flood report in Chengannur, Alappuzha. Open it as admin and check the saved **Location & alert check**. The district alert covers Chengannur and produces `MATCH`.
3. Select **Predict severity** to run the bundled model against the reported situation. The saved assessment uses Low, Medium or High; the model's Moderate label maps to Medium. No external API key is required for severity prediction.
4. Read the **Report summary** draft. It is generated automatically from report excerpts and submitted location, people and help fields, using local extraction without an API key. Older reports have **Generate summary**. Review or edit the assessment summary, set **Investigation needed** to Yes, and select **Save assessment**. Refreshing the draft preserves reviewed text, severity and investigation findings. Claims remain unverified; always read the original report.
5. Enter an investigator's name and select **Start investigation**. Save findings while In progress, use **Reassign investigator** if needed, then choose Completed and save again. Completed investigation findings remain available for review and cannot be edited.
6. Expire the demo alert and select **Analyze location** again to demonstrate `NO_MATCH`. An unknown or ambiguous location produces `UNCERTAIN`. No matching alert does not establish that the report is false or the area is safe.

Admins can also select **Run Gemini agent** after configuring a Gemini API key. The optional agent uses the OpenAI Agents SDK with the configured Gemini model (`gemini-3.1-flash-live-preview` by default) and controlled location extraction/active-alert tools. Deterministic geography and the severity classifier work without that key. Missing provider configuration or failed agent runs produce a labelled local fallback.

To enter a Gemini key locally with hidden input:

```powershell
.\.venv\Scripts\python.exe -m scripts.configure_gemini
```

Setup reruns preserve private Gemini options, custom configuration and comments. The app reads the saved key on the next agent request. `GEMINI_API_KEY` or `GEMINI_API_KEY_FILE` can also be supplied through local configuration. See [Athul's location and agent implementation](docs/week2-athul.md) for technical details; its original branch-specific Linux launch instructions are historical.

Rescue progress, relief, shelters, chatbot, notifications, Malayalam report translation and case closure remain later-week work. Curated Malayalam place aliases are supported by the geography tool.

## Stop and verify

```powershell
.\scripts\stop.ps1
```

Stop checks the recorded application's PID, creation time and command line before terminating it, and shuts down only `.runtime/postgres` belonging to this workspace. Start reuses this workspace's existing application when it is already running.

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m scripts.verify_local
.\.venv\Scripts\python.exe -m scripts.check_location_agent
# Optional client-state checks; Node is needed only to run this test.
node tests/session_client.cjs
```

The readiness command requires the application to be running and checks PostgreSQL, the home page, API docs and the authentication gate without creating a report. The location-agent check above uses local geography and current database alerts; it makes no provider call. Automated tests isolate their records, and optional PostgreSQL checks use temporary schemas. Browser demonstration is a separate check from automated tests.

API paths include authentication and `/api/users/me`, `/api/incidents/` and report detail/history/status, team assignment and `/api/teams/assignments`, `/api/alerts`, incident location analysis, `/api/ai/predict-severity`, and `/api/admin/incidents/{id}/analysis` or `/investigation`. Consult the running API docs for exact methods and request bodies. Protected JSON APIs require the bearer token returned by login; assessment, prediction and investigation actions require an admin.

If setup fails, confirm the PostgreSQL binary path and port availability. If startup fails, check `.runtime/postgres.log`, `.runtime/web.log` and `.runtime/web-error.log`. Do not replace the generated database password while retaining an existing cluster. If PowerShell's script policy blocks a command, run it explicitly with `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup.ps1` and then the corresponding `start.ps1` command.

See [Week 2 merge notes](docs/WEEK2-MERGE.md) for current branch provenance, integration fixes and validation. [Week 1 integration notes](docs/INTEGRATION.md) and [Week 1 validation results](docs/VALIDATION.md) document the earlier baseline. Original React files are preserved in branch history; the active frontend uses HTMX templates and static assets. Older member-specific documents describe their original branches.

See [the 21 October feature audit](docs/WEEK2-AUDIT.md) for branch comparisons, summary implementation and current verification evidence.
