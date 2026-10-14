# Week 1 validation

## Authentication parity update — 14 October 2026

Verified locally against the running PostgreSQL application on Windows, using
synthetic QA accounts and reports. Existing application accounts, sessions, teams,
reports and history were preserved through the membership migration.

| Check | Result |
| --- | --- |
| Python suite including isolated PostgreSQL migration tests | **79 passed**: original 52, 21 auth UI regressions, 4 SQLite membership checks, 2 PostgreSQL migration checks |
| Browser client state tests | **18 passed** using Node VM fixtures: per-tab credentials, bootstrap/history revalidation, expiry, logout HTTP/transport failures and retry recovery |
| Existing PostgreSQL data migration | **Passed**: foreign key added, repeated initialization succeeded, existing account/session/team/report/history rows unchanged |
| PostgreSQL migration safety | **Passed**: temporary schemas confirmed preserved IDs/password hashes/sessions, repeat migration, rejection of dangling memberships and referenced-team deletion, refusal of preexisting orphans |
| Same-browser tabs | **Passed**: citizen registration, independent admin/team login, reload/direct links, account facts, real permission matrix, citizen logout while admin remains signed in |
| Browser Week 1 workflow | **Passed**: synthetic report, review, verification, assignment to a synthetic team, citizen/team four-state timeline |
| Session/history behavior | **Passed**: Back/Forward revalidates, Back after logout requires login, expiring only the synthetic admin session displays the expiry notice |
| Service outage handling | **Passed in isolated tests**: profile failures preserve authentication and offer valid GET retry links; logout failures show unconfirmed revocation; history refresh failures expose retry |
| Browser console and source checks | **Passed**: no errors in the three QA tabs, JavaScript syntax and Git whitespace checks |

All three synthetic browser accounts, their sessions, the synthetic report/history
and its response team were removed. Sanitized browser evidence and screenshots
remain only in ignored `.runtime/qa/`. The existing application's data was not reset.
Outages were simulated in isolated tests; the active application's database was
not deliberately taken offline to simulate a failure.

The default Python suite runs **77 tests and skips the 2 opt-in PostgreSQL cases**.
To include PostgreSQL safely without printing connection details:

```powershell
.\.venv\Scripts\python.exe -B -c "import os,subprocess,sys; from backend.config import get_settings; os.environ['RESQ_TEST_POSTGRES_URL']=get_settings().database_url; raise SystemExit(subprocess.call([sys.executable,'-B','-m','pytest','-p','no:cacheprovider']))"
node tests/session_client.cjs
```

The optional Playwright smoke script now uses tabs in one shared browser context
and checks that citizen logout leaves the admin authenticated. This revised script
was syntax checked; the browser walkthrough above was performed through the
Codex browser tools rather than by executing that script.

## Original integration record — 10 October 2026

The integrated application was verified locally on Windows with Python 3.13.9,
PostgreSQL 18.6, and Chrome. The application runs at `http://127.0.0.1:8013`;
its isolated database runs on port `5443`.

| Check | Result |
| --- | --- |
| Automated backend and HTML integration tests | **52 passed**: 27 original authentication checks, 22 combined workflow checks, 3 HTML/HTMX integration checks |
| PostgreSQL assignment races | **Passed**: two reports competing for one team, and two teams competing for one report; each returned one success and one conflict |
| Chrome complete workflow | **Passed**: registration → submission → review → verification → assignment → citizen timeline/team view → logout |
| HTMX behavior | **Passed**: navigation updates HTML without reloading the page; incorrect-login feedback renders; history caching is disabled; back navigation after logout requires login |
| Responsive layouts | **Passed**: desktop 1440 px and mobile 390 px; login, report form and status screens inspected; no horizontal overflow in tested mobile screens |
| Persistence | **Passed**: assigned report and all four timeline entries survived stopping and restarting both the app and PostgreSQL |
| Setup/start/stop | **Passed**: initial setup, repeated setup preserving accounts, application startup, workspace-only shutdown and restart |
| Source checks | **Passed**: Python compilation, JavaScript syntax, PowerShell parsing, dependency consistency, Git whitespace checks and source hygiene |

The default automated suite uses isolated SQLite databases and does not prove
PostgreSQL row-lock behavior. The separate live PostgreSQL checks above cover the
two tested assignment races. Browser checks used the real PostgreSQL application.
Temporary browser/concurrency records were removed after verification and the demo
team was returned to availability. Screenshots and sanitized check results remain
in the ignored `.runtime/qa/` directory.

Useful verification commands from the project root:

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m scripts.verify_local
```

The first runs the current automated suite; the second checks the running application
and PostgreSQL without modifying reports. The standalone live concurrency script
is `tests/postgres_concurrency.py`. The optional browser script is
`tests/browser_smoke.cjs`; it requires Playwright and installed Chrome for testing,
which are unnecessary to run the application itself. Browser verification creates
a synthetic account/report and assigns the demo team; clean those test records
before repeating that script against the same database.

Inherited Pydantic/date and dependency deprecation warnings remain visible in test
output. They did not fail the checks; unrelated backend modernization was kept out
of this integration. This validation covers the local Week 1 workflow, not public
deployment or later-week functionality.
