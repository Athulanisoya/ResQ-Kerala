# Week 1 validation — 10 October 2026

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

The first runs the 52 automated checks; the second checks the running application
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
