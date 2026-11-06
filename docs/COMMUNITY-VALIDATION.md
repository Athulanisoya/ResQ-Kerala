# Community feature validation · 5 November 2026

Implemented and verified in the requested order: offline reporting (1),
volunteer registration/shifts (2), private family safety (3), shelter facility
filters (5), and bilingual household preparedness (6). The active frontend
remains HTMX and follows the Coast & Canopy theme.

## Verification

- Full Python regression suite: **876 passed, 41 skipped**, no failures.
  Skipped checks include opt-in PostgreSQL/live integration checks; they are not
  counted as passing. The new PostgreSQL scenarios below were run separately.
- Independent PostgreSQL sessions in disposable schemas verified retry-safe
  reports, competing volunteer places and overlapping shifts, invitation
  acceptance/revocation, check-in/leave, competing facility confirmations and
  household-plan version conflicts. Offline migrations also passed.
- JavaScript tab-session suite: **19 passed**. All **67 templates** compiled;
  Python compilation and JavaScript syntax checks passed.
- Browser workflows passed for offline reload/reconnection/lost-response retry,
  volunteer approval/signup/cancellation, private family invitation/sharing/
  withdrawal, facility confirmation/filter polling, bilingual plan saving and
  printing. New screens were checked at **320px and 1440px**.
- Header checks passed for all three roles at seven widths from 320 to 1920px,
  including short landscape scrolling, keyboard dismissal and active links.
- Computer-use review checked the actual volunteer page, private circle creation,
  service navigation, English/Malayalam rendering and logout. Screenshots were
  visually reviewed, including the print layout. The print button uses saved
  values, a white canvas and restores the original theme after print/cancel.
- Docker application, PostgreSQL and Ollama were healthy. Runtime dependency
  validation reported no broken requirements. Readiness confirmed HTMX,
  PostgreSQL and the configured tool-capable `gemma4:e4b-it-q4_K_M` model.

Browser tests are `tests/offline_reports_browser.cjs`,
`tests/volunteers_browser.cjs`, `tests/family_safety_browser.cjs`,
`tests/shelter_facilities_browser.cjs`, `tests/preparedness_browser.cjs` and
`tests/header_browser.cjs`. They require local demo accounts in the ignored
runtime directory and Playwright available to Node. Test screenshots and the
full regression log are under ignored `.runtime/qa` and `.runtime` paths.

Synthetic browser fixtures were closed, cancelled or deactivated through normal
application workflows; audit history remains. Existing records and prior local
changes were preserved. Validation completed before publication.

The verified local application runs at `http://127.0.0.1:8014`. Donations remain
pledges and SMTP remains deferred. Offline sending requires an open browser and
valid citizen session; device drafts are not an encrypted vault. Preparedness
wording is source linked and does not claim an official translation or current
location-specific evacuation directions.

## Offline resilience follow-up · 6 November 2026

- Focused reporting/session regression tests: **38 passed**.
- Five additional browser scenarios passed: stalled requests with responsive
  local saving, transient failures while the browser remains online, delivery
  after reopening another app page, session renewal/account isolation, and
  duplicate-safe recovery from lost or malformed successful receipts.
- The original offline workflow passed again at 320px and 1440px, including
  cached reload, editing, reconnection, private caches and receipt verification.
- Nine deterministic service-worker fault/privacy checks passed. Temporary
  server failures and stalled requests use prepared public form/assets;
  decorative image downloads do not block offline preparation.

These follow-up browser checks used the existing local Python/PostgreSQL app at
`http://127.0.0.1:8013` because Docker Desktop encountered a startup error.
Automatic sending still requires an open application and valid citizen session;
saved waiting reports resume on reopening and signing in. Unsubmitted drafts
remain local.
