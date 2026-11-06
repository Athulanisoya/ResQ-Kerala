# Area alerts, shelter reminders, waiting lists and team suggestions

All delivery is through the existing private **Notifications** inbox and header
unread badge. No SMTP, SMS service or messaging account is required.

## Follow area alerts

Open **Official alerts → Follow district and locality alerts**, **My updates →
Follow area alerts**, or **More services → Follow area alerts**.

Each account follows catalog districts or localities privately. A district follow
includes alerts for its localities. A locality follow includes that locality and
district-wide alerts, but excludes sibling localities. Overlapping follows create
one notification per observed alert event. Following an area checks current active
alerts immediately; later checks notify activation, changed content/coverage,
rescheduling, and ending of previously delivered alerts. Unfollowing stops that
area's future notifications. Green or an ended alert is not proof of safety.

Scheduled starts and expirations are checked automatically. Checks observe the
latest saved alert state; intermediate edits between checks are not an immutable
alert-change feed. An alert that started and ended during downtime and was never
delivered is not presented as a new active warning after restart.

## Capacity confirmation reminders

Staff confirmation is separate from the record's last activity time. Creating a
shelter or explicitly saving its reviewed capacity counts confirms capacity.
Reservations, offer holds, cancellations and page polling do not confirm it.
The shelter lists, map details and assistant expose the confirmation time.

Defaults:

- Remind the designated Shelter team's active accounts after 30 minutes.
- Repeat unresolved reminders every 60 minutes.
- Escalate to administrators after 120 minutes since confirmation.
- Notify administrators immediately if the confirmation is unknown or no active
  designated reception account is available. Closed shelters are excluded.

Reminders never change occupancy, capacity or confirmation timestamps. Saving a
new capacity confirmation ends that stale episode. Administrator controls are at
**Administration → Manage automation timing and check status**, also available
under More services. Settings use version checks to protect concurrent edits.

Historical confirmation backfill uses attributable staff capacity snapshots,
excluding registration/offer activity. Missing evidence stays unknown. Automatic
capacity audit entries have a null actor, rather than impersonating a citizen.

## Shelter waiting lists

Citizens open **Waiting list / offers** from a shelter card, map popup or shelter
registration page. **More services → My shelter waiting list** shows their own
entries across shelters. Reception access remains limited to administrators and
the designated Shelter team. Origin, contact and support notes remain private.

The queue considers waiting groups in first-in order and offers space to groups
that fit. A group that cannot currently fit remains waiting with an explanation;
smaller fitting groups may proceed. Offers hold real capacity and notify the
citizen. The default acceptance deadline is 15 minutes and is shown in IST.
Accepting converts the hold into a normal reservation without deducting capacity
twice. Arrival still requires reception confirmation.

Expired, cancelled or ineligible offers release holds once. Closing a shelter
releases outstanding offers and pauses waiting groups. Direct bookings and
ordinary capacity edits respect held spaces. Confirmed reservations and arrived
guests have no automatic expiry. Entry history is retained, and expired groups
can explicitly rejoin. Retries and current-version checks protect acceptance and
cancellation. Offer records poll separately from the join form, preserving drafts.

## Suggested response teams

Administrators configure **Administration → Response teams → Operating areas &
capabilities**. Areas come from the existing district/locality catalog. Capability
tags are administrator declarations, not certifications or AI-generated facts.

On a report, **Suggested response teams** ranks available teams of the selected
type with active accounts. Exact locality coverage ranks above district coverage;
unknown coverage or uncertain incident locations are explicitly caveated. Known
outside-area teams and missing requested capabilities are excluded. Current valid
human location confirmation takes precedence over the original extractor result.

The administrator chooses **Assign this team** using the existing assignment
workflow. Assignment still requires a verified, unassigned report and rechecks
availability under locks. Recommendations do not automatically assign teams,
change report severity or determine safe travel routes.

## Operation and checks

Automatic checks run inside the application while it is running, every 30 seconds
by default. PostgreSQL job locks and per-entity transaction locks coordinate
multiple app processes. Durable subscription deliveries, queue entries, holds and
notification event keys survive restarts. Jobs commit independently so one failed
job does not undo another completed job. Errors are retried without recording
private exception text in the public status.

`AUTOMATION_ENABLED=false` disables background checks for maintenance; it does
not prohibit explicit citizen actions or administrator **Run checks now**. Set
`AUTOMATION_POLL_SECONDS` between 5 and 300 to change the cadence. Docker passes
these optional `.env.docker` settings to the app. Timed offers need a running app
to issue/expire automatically; acceptance always revalidates the actual deadline.

The admin settings screen shows the last cycle and each job's status. **Run checks
now** performs the same checks without exposing a client-supplied clock.

Run `python -m pytest` for regression checks. Optional real PostgreSQL tests use
`RESQ_TEST_POSTGRES_URL`, create isolated schemas and clean them afterwards.
`tests/automation_browser.cjs` exercises the four user flows and responsive
layouts against the Docker app with clearly labelled synthetic fixtures.
