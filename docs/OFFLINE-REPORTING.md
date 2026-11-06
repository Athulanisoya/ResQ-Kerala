# Offline incident reporting

Citizens can save incident drafts on their current device and explicitly queue
them for submission when connectivity returns. The existing FastAPI and HTMX
report/review workflow remains the destination for every submitted report.

## Citizen workflow

1. Sign in online with a citizen account. Open **New report** once while
   connected to prepare incident reporting for offline use. There is no separate
   offline tab or reporting page.
2. Enter the location, description, optional number of people and help needed.
   **Save draft** does not submit it. **Submit report** validates
   the details and places the report in the waiting queue.
3. While offline, the page retains drafts and waiting reports in IndexedDB. The
   same **Report an incident** form can be reopened or reloaded at `/reports/new`
   after its public shell and assets have been prepared by the service worker.
   Drafts and waiting submissions remain inline below the incident form controls.
4. On reconnection, waiting reports are retried using the current tab's signed-in
   citizen session, including while another application page is open. Reopening
   the application or returning to its tab also resumes the queue. A successful
   server receipt changes the row to **Submitted** and provides its reference
   and a link to the normal report page.
5. Edit unsent drafts, retry waiting reports, or remove local drafts/receipts.
   Removing a local record does not delete a report already received by the
   server. After an interrupted submission, check **My reports** before creating
   a replacement: the server may have received it even when no receipt arrived.

The UI distinguishes **Draft · not sent**, **Waiting to send**, **Needs
attention**, and **Submitted**. It does not treat a browser connectivity signal
as proof of server receipt.

Saving a draft or adding another report to the waiting queue does not wait for
an earlier network request. Connection checks and submissions have a 10-second
deadline, including receipt downloads. Interrupted requests, unverified receipts,
HTTP 408/425/429, and server errors keep the report waiting and retry with a delay
that grows from one second to at most 30 seconds. Periodic checks also detect
recovery when the browser continues to report that it is online throughout an
unstable connection. Each attempt retains the original submission UUID.

Only waiting reports are delivered automatically. Drafts remain drafts until
the citizen explicitly submits them. If the session expires, the queue pauses
until the same citizen signs in again; another account cannot send it.

## Storage and authentication

- Only a public copy of the regular report form (`/offline/report-form`, an
  internal cache resource) and its static assets are service-worker cached.
  Legacy `/offline-report` bookmarks redirect to `/reports/new`. Offline New
  report links use the canonical document URL rather than an authenticated
  HTMX request.
  Authenticated pages, reports, API responses and notifications are not cached.
- Draft content lives in the browser's IndexedDB, scoped by account ID for the
  application UI. No password, bearer token or CSRF token is copied into the
  queue or service-worker cache. The current tab's existing session authenticates
  each request.
- A server-side `/api/users/me` check verifies the current account and citizen
  role before synchronization. Expired or changed sessions leave reports saved
  for the appropriate citizen to resume after signing in online.
- Device storage is not an encrypted vault. Local drafts remain on the device
  until removed or browser site data is cleared; use the remove controls on
  shared devices. Clearing browser storage also removes unsent drafts.
- The queue is limited to 30 local drafts/receipts per account. Storage failures
  are shown explicitly and keep the form open so the citizen can retain the
  details.

## Retry-safe backend contract

`POST /api/incidents/` accepts an optional `client_submission_id` UUID alongside
the existing report fields. The browser creates this UUID before its first
submission and retains it for every retry of that saved report.

- A unique database key on `(user_id, client_submission_id)` makes simultaneous
  retries from independent tabs or requests create at most one incident.
- The original normalized create payload has an immutable SHA-256 fingerprint.
  An identical retry returns the original incident with HTTP 201, its current
  status, the same reference and the same submission UUID. It does not repeat
  analysis snapshots, history records or notifications.
- Reusing a UUID with different report details returns HTTP 409 and does not
  change the original report. A previously attempted draft is kept immutable
  by the UI when its outcome is uncertain. Validation failures (HTTP 422) can be
  corrected before retrying.
- Keys are scoped to the authenticated citizen, so one account cannot discover
  another account's report by guessing a submission UUID. Existing caller
  requests without a UUID retain the ordinary create-each-time behavior.
- Fingerprints are internal and are not exposed in API responses. New nullable
  columns and a unique index are added without modifying existing incidents.
  Migration is repeatable for PostgreSQL and test-only SQLite.

## Limits

The reporter needs a modern browser with IndexedDB and service workers on HTTPS
or a supported localhost secure context. A device must be prepared while online;
an unvisited application cannot be loaded for the first time without a network.
Draft editing can continue in an already-open form if offline shell preparation
fails, with an explicit preparation message. Essential public form assets are
prepared separately from optional background images. A stalled navigation to
the form falls back to its prepared public copy, while local draft storage
remains independent of both preparation and delivery.

Automatic sending requires the application to be open with a valid citizen
session. It does not send from a closed browser or persist credentials for
background delivery. Drafts alone are never automatically sent. Attachments can
be added through the existing report page after submission; file uploads are not
part of the offline queue.

## Verification

Backend tests cover identical replay, normalization, every changed report field,
account-scoped keys, invalid UUIDs, existing no-key callers, review preservation,
and absence of repeated history/analysis/notification side effects.

```powershell
.venv/Scripts/python.exe -m pytest backend/tests/test_offline_reporting.py tests/test_offline_reporting_migration.py backend/tests/test_workflows.py
```

The focused backend/regression run passed 36 tests, with one PostgreSQL-only
migration test skipped when no explicit test URL was supplied. The independent
PostgreSQL run passed all four offline concurrency/migration checks. Its race
tests force every initial lookup to see no existing report before competing
inserts and use separate database sessions in a randomly named disposable schema.
No live application records are used by these tests.

`tests/test_offline_ui.py` checks the public shell, citizen controls and HTMX
retry forwarding. `node tests/offline_reports_browser.cjs` (with Playwright
available) checks real offline reload, draft editing, reconnection, a deliberately
lost successful response, account isolation, credential-free public caches and
mobile/desktop layout. Synthetic submitted browser-test reports are closed
through the ordinary response workflow; fixture accounts are deactivated.

`node tests/unstable_reporting_browser.cjs` additionally exercises stalled
connection checks and submissions, saving during another pending delivery,
transient HTTP failures without an offline event, recovery from other pages and
after reopening, session renewal and account isolation, and lost or malformed
successful receipts. It checks that every queued UUID produces exactly one
server report and that unsubmitted drafts remain local.

`node tests/offline_worker.cjs` runs nine deterministic service-worker fault
and privacy checks without a running application: essential-only preparation,
cached fallbacks for transient failures and stalled bodies, request exclusions,
and preservation of a working cache when an update cannot be installed.

```powershell
# RESQ_TEST_POSTGRES_URL must select a test-accessible PostgreSQL instance.
.venv/Scripts/python.exe -m pytest tests/test_offline_reporting_postgres.py tests/test_offline_reporting_migration.py
```

Browser tests for the frontend are maintained separately with the offline
reporter and validate actual disconnected/reconnected submission flows.
