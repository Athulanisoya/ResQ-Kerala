# Athul's Weeks 1–4

Scope comes from the supplied `ResQ_Kerala_Member_Weekly_Guide.pptx` (Athul's weekly slides, especially slides 17 and 23) and `ResQ_Kerala_Complete_Project_Discussion.md`. The guide's React paths describe feature ownership in a reference implementation. They are not commands to modify another checkout. This implementation continues the current FastAPI/HTMX app and existing Week 1/2 APIs.

Only Athul's assigned screens and the shared API/data contracts they require are included. Other members' shelter, chatbot, translation and AI work is not represented as implemented here.

| Week | Implemented behavior | Main implementation |
| --- | --- | --- |
| 1 | Citizen registration/login, tab-scoped sessions, report submission/list/detail/history, role navigation, admin review/assignment, team assignment view | `web/app.py`, templates, session client, auth/incidents/admin/teams APIs |
| 2 | Sourced Kerala location extraction, admin alert create/edit/expire screens, active-alert matching with MATCH/NO_MATCH/UNCERTAIN | Location/alert services, templates and API tests; integrated summary/assessment/investigation screens also retained |
| 3 | Accept → En route → In progress → Resolved, audited stock, relief requests/assignment, partial deliveries/remaining demand, rescue-to-relief handoff, former-team history | `web/operations.py`, `operations.html`, operations models/router/service |
| 4 | Private updates/unread polling/read controls, linked-case navigation, clarification question and retained citizen reply, full status/search filters, final admin closure | `web/communication.py`, updates/clarification templates, communication models/router/service |

## Demonstrate Week 3

1. Submit a synthetic citizen report; verify and assign it as admin.
2. Sign in as its assigned rescue team and open the report. Accept it, mark En route, then Start field response.
3. Admin opens **Relief & supplies**, creates stock with a unit and records a linked supply request. Assign an available relief team. Account/team provisioning remains administrative; public registration creates citizens only.
4. The assigned relief team records a partial delivery. Check the immutable requested item/unit, delivered amount, remaining demand, delivery history and reduced stock. Overselling and unit mismatches are rejected atomically; retrying an identical delivery key does not subtract twice.
5. Admin may hand an in-progress rescue case to an available relief team. The original team sees only its retained task snapshot after handoff. The new team accepts and progresses its task.
6. Complete all linked relief, then resolve the incident. A team becomes available only after all its work is finished.

## Demonstrate Week 4

1. Admin opens a report and requests a required clarification.
2. Citizen opens **My updates**, follows the linked report and sends a reply. Reload to verify the saved reply, original report and timeline.
3. Follow team acceptance/progress notifications through Resolved. An admin closes the case after required questions and relief are complete.
4. Citizen filters **My reports** to Closed and searches its reference/location. The final screen retains the history and reply.
5. Read one update or mark all read. The sidebar polls the authenticated unread count every 30 seconds while visible; HTMX owns the timer and removes it with the element. Main-page refreshes also refresh the badge. Session expiry uses the existing per-tab sign-in recovery.

## Data and permissions

New tables are created by the existing schema initialization; existing incident/account columns and records are preserved. Status strings extend the original lifecycle. Writes lock the parent incident and relevant request/stock rows, validate the entire delivery basket, then commit state/history/notifications together. Stock quantities use fixed-precision decimals.

Notifications are scoped to active reporting citizens, admins and the current assigned team. Only the reporting citizen can answer a question, and only admins can request/cancel questions or close cases. Completed replies and delivery snapshots are retained. Unanswered required clarification blocks closure. Unfinished relief blocks both resolution and closure. No email/SMS or external notification service is used.

## Validation

Validation on 22 October 2026:

- **323 Python tests passed**, including all seven opt-in PostgreSQL checks (five operations/concurrency checks and two existing migration checks); no skips. Two pre-existing Pydantic configuration deprecation warnings remain.
- **19 JavaScript session/update-refresh checks passed**.
- Original PostgreSQL assignment race script passed both competing-assignment scenarios and removed its three marked reports/teams.
- `pip check` reported no broken requirements.
- Live localhost checks passed citizen/admin/team HTML pages, authenticated APIs, summary/clarification report sections and workspace PostgreSQL. Test sign-in sessions were revoked; business records were preserved.
- Visual browser verification was blocked by the browser tool's security policy. HTML/API integration tests execute the form workflows, but this is not a claim of a completed visual browser test. The optional Gemini live-provider path was not run; local geography, summary and severity are covered.

Reproduce the standard checks with:

```powershell
.\.venv\Scripts\python.exe -m pytest -o addopts='' -q
node tests/session_client.cjs
.\.venv\Scripts\python.exe -m scripts.verify_local
.\.venv\Scripts\python.exe -m scripts.verify_athul_workspaces
```

Optional PostgreSQL tests use `RESQ_TEST_POSTGRES_URL` privately and create disposable schemas. Live workspace checks sign in and revoke the generated test sessions without changing incident, inventory or relief records. Local extractive summaries, geography and severity need no provider key. The location agent now uses local Gemma 4 through Ollama; see [the provider migration and current verification](OLLAMA-MIGRATION.md) for setup and the successful live tool/form checks.
