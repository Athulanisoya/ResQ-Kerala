# Week 2 feature audit - 21 October 2026

Compared freshly fetched `origin/main` at `4df359f` with all four requested member branches. Every branch tip is already an ancestor of main; no branch has new unmerged commits. Branch ancestry alone does not establish feature completeness.

| Branch | Tip | Evidence and result |
| --- | --- | --- |
| athul-week2 | 09fff8a | Gazetteer, deterministic location extraction, alert scheduling/edit/expiry/matching and Gemini adapters retained. Geography and alert modules match the branch source. |
| Vidya-week2 | b0974ad | Bundled severity pipeline retained byte-for-byte; High/Moderate/Low mapping retained. No summary generator exists in this branch. |
| aryaweek2 | 501d245 | Analysis storage and investigation lifecycle retained. Its nullable summary field is only manually saved text. No summary generator was supplied. |
| week2-maanaz | 3297bdb | Per-tab authentication, account/permissions pages, team membership constraints and atomic team assignment retained. This tip predates the other Week 2 feature branches. |

## Gaps found and corrected locally

1. **Automatic summary generation was absent.** The original integration merged the supplied code but did not implement the missing summary requirement. New reports now save an automatic local extractive draft in the report transaction. Authorized owners, admins and assigned teams can read it. Admins can generate drafts for older reports and refresh them. Drafts use a separate `incident_summaries` table, so regeneration does not overwrite reviewed summaries or other analysis fields, status, assignments, investigations or original reports.
2. **Severity prediction used a stale full-assessment PUT.** Another admin's changes during inference could be lost. The incident-bound API now predicts from the stored report and updates only severity on the latest locked assessment. The UI preserves unsaved form edits.
3. **Investigation reassignment was available only through the API.** The active-investigation page now exposes the existing reassignment behavior and preserves findings. Completed investigations remain immutable and expose no reassignment form.
4. **Setup rewrote private environment configuration.** Reruns now update only setup-owned keys using an atomic copy, preserving Gemini keys/model/budgets, custom settings and comments. Tests use synthetic credentials and verify failed updates leave the original intact.
5. **Review caught two edge cases in the new summary feature.** Line wraps are normalized within a sentence before ranking so `No one was\ninjured` retains its negation. An intentionally cleared reviewed summary stays blank after reload/refresh instead of being silently replaced by a generated draft.

## Summary behavior and limits

The summary method is `local_extractive_v1`: up to three selected report excerpts plus explicitly submitted location, people count and requested help. It prioritizes relevant incident clauses, preserves selected wording/negation and Unicode, and bounds drafts to 1,200 characters. It runs offline, requires no model download or API key, and does not claim to verify reports or infer deaths, casualties, severity or response decisions. The original report stays visible. This is extractive summarization, not a generative LLM feature.

`GET /api/incidents/{id}/summary` follows the incident's ownership/team access rules; `POST` on that path is admin-only. New-table creation is handled by existing startup initialization; no existing incident/assessment column is changed or destructively migrated. Old records are preserved; generate their drafts explicitly from the report page.

## Verification

- Final complete pytest run with PostgreSQL migration checks enabled: **259 passed, zero skipped, zero failures**. JUnit evidence: `.runtime/qa/summary-tests.xml`; console log: `.runtime/qa/pytest-summary.log`.
- JavaScript tab-session regression checks: **18 passed**.
- PostgreSQL assignment concurrency: both competing-report/competing-team scenarios passed with one success and one 409 conflict each. All three synthetic concurrency reports and three teams were removed by ownership-checked cleanup; evidence: `.runtime/qa/postgres-concurrency.json`.
- `pip check`: no broken requirements. Source whitespace/conflict checks passed.
- Restarted server passed PostgreSQL health, home page, Swagger/OpenAPI and unauthenticated report gate readiness checks. Local geography CLI resolved Aluva and returned NO_MATCH without provider calls.
- Actual browser against PostgreSQL: independent citizen/admin sign-ins; synthetic multiline report automatically saved a visible summary preserving “No one was injured”; admin prediction preserved unsaved manual text; saving assessment then refreshing the draft preserved reviewed text; investigator reassignment preserved findings; completion hid reassignment controls. Reload preserved the generated summary. Browser console contained no warnings/errors.
- Direct PostgreSQL check confirmed summary input hash matches the unchanged original report, manual assessment remains separate, and reassigned/completed investigation is stored. Evidence: `.runtime/qa/summary-live.json`, screenshot: `.runtime/qa/summary-browser.png`.

The app is left running at `http://127.0.0.1:8013`. One clearly labelled synthetic summary-audit report (#6) remains locally for review; existing user reports were not changed. The two existing Pydantic class-config deprecation warnings remain.

No live Gemini request or external data export is needed for these fixes. Provider transport/function-tool behavior is exercised by simulated transport tests; successful live provider execution is a separate check requiring configured credentials. Passing model integration checks establishes executable behavior and preservation of the supplied pipeline, not a measured real-world severity classification accuracy.

The fixes were prepared and validated on `fix/week2-summary-audit` before the user authorized publication to `main`.
