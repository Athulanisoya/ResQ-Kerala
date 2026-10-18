# Week 2 local integration

The local branch `integration/week2-all` combines these fetched branch tips:

| Requested branch | Fetched tip | Features retained |
| --- | --- | --- |
| `week2-maanaz` | `3297bdb` | Tab-isolated authentication, account/permissions pages, team membership integrity, atomic response-team assignment |
| `athul-week2` | `09fff8a` | Kerala gazetteer, location extraction, saved alert matches, alert management, optional Gemini Live location agent, Swagger bearer auth |
| `aryaweek2` | `501d245` | Reviewed incident analysis, investigator assignment, findings/actions and investigation completion |
| `Vidya-week2` | `b0974ad` | Trained TF-IDF/logistic regression severity pipeline and prediction API |

`week2-maanaz` matched `main` and was already an ancestor of Athul. Arya was based on Athul. Local merge commits preserve each requested branch's history; no remote branch or pull request was created or updated.

## Integration fixes

- Restored private `.env` loading and a safe `.env.example`; removed machine-specific configuration from the example.
- Kept isolated PostgreSQL at 127.0.0.1:5443 and the app at 127.0.0.1:8013, with this folder's own `.runtime` data and virtual environment.
- Registered every API router, including alerts, location analysis, severity and investigations. Retained Swagger bearer authentication and PUT support for assessment updates.
- Preserved tab bearer sessions, CSRF checks, account and workspace-permission pages, alert management and location tools when adding investigation actions.
- Registered all HTML actions before the catch-all API mount, and added the missing investigation UI.
- Added an admin severity action using the shipped local pipeline, normalized its High/Moderate/Low output to the assessment's HIGH/MEDIUM/LOW values, and preserved existing non-severity assessment fields.
- Corrected completed-investigation guards, validated reviewed severity values, removed request-data debug prints and retained existing database column compatibility.
- Added feature and integration regression coverage. Provider-independent core features require no external API key.

## Runtime

Run `scripts/setup.ps1`, then `scripts/start.ps1` from this folder. Use `scripts/stop.ps1` to stop only this workspace's recorded application and database. Generated sign-in details are in the ignored `.runtime/demo-accounts.json`; credentials, database files and the virtual environment stay local.

The inherited database/schema name `resq_week1` is retained for compatibility; the application version is `2.0.0-integrated`. Investigation completion is separate from the incident status timeline, which still ends at team assignment.

## Validation

Validated on 18 October 2026 on Windows with Python 3.11.9, PostgreSQL 18, and the merged requirements.

- Full pytest suite: **221 passed, 2 skipped** in the default isolated run. The two skipped PostgreSQL migration cases were then enabled through the private local database URL: **6 passed** in `tests/test_team_membership.py`, including those two cases. This covers all 223 collected cases across the runs.
- Client session checks: **18 passed** using `node tests/session_client.cjs`.
- `pip check`: no broken requirements. Source diff/conflict-marker checks passed.
- Running-app readiness: PostgreSQL connection, health, home page, API docs/OpenAPI and unauthenticated incident gate passed at `http://127.0.0.1:8013`.
- Browser against the real database: independent admin/citizen tabs; synthetic alert creation; report submission with a saved Aluva alert match; local model prediction HIGH; reviewed assessment save; investigator assignment and completed findings; review/verification; team assignment reflected in the citizen timeline.
- Live API checks also verified the response-team assignment and denied admin assessment access to the team, expired the synthetic alert, and confirmed a fresh location result of NO_MATCH. The browser automation could not complete the alert's native confirmation dialog, so expiry was verified through its authenticated API instead.
- Optional Gemini agent is unconfigured in this checkout (`configured=false`). Provider transport/tool tests pass, but no live Gemini call was made and no API key was copied from another workspace.

One clearly labelled synthetic report remains as report #1 with completed investigation and assignment to the local demo team; the synthetic alert is expired. These records are only in this folder's private database. The app and PostgreSQL are left running. A browser screenshot is saved at `.runtime/qa/merged-report.png`.

The restricted process sandbox stalled the first test/database startup attempts. Tests and database initialization completed outside that sandbox. The incomplete first cluster was preserved at `.runtime/postgres-incomplete-sandbox`; the working cluster is `.runtime/postgres`.

Existing Pydantic class-config deprecation warnings remain from the branch baseline. No GitHub push, PR, deployment or external-provider request was performed.
