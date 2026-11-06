# Volunteer hub

Open **More services → Volunteer hub**, or **Community → Open volunteer hub**.
Citizens submit their catalog district/locality, ward, declared skills,
availability and consent to administrator review. Approval never changes their
account role. Administrators approve, reject or suspend an application with a
reason. Revisions require a fresh review and release future signups, with a
visible warning, retained history and private notifications.

Administrators create future shifts (up to 24 hours, 1–1,000 places) with a
meeting point, instructions, required declared skills and an optional existing
open shelter. Approved volunteers explicitly join and can cancel future duties.
Shift row locks prevent excess bookings; participant row locks prevent concurrent
overlapping signups. Retries return the same signup. Version checks protect edits,
reviews, cancellations and attendance. Booked shifts cannot be rescheduled;
cancel and publish a replacement. Capacity, times, skills and shelter state are
rechecked on joining.

Only administrators see applications and private rosters. Citizen listings show
shift information and only that citizen's signup history. Response-team accounts
have no roster access. Skills are self-declared and administrator reviewed;
professional certification checks remain part of the administrator's review.

Attendance follows registered → checked in → completed, or registered → no show.
Check-in requires the scheduled start, an active citizen and current approval;
completion/no show requires the scheduled end. Events retain actor, version and
time. All notifications are in-app; this feature does not send emails or SMS.

Run `pytest tests/test_volunteers.py tests/test_volunteers_ui.py`. Optional
`tests/test_volunteers_postgres.py` uses disposable PostgreSQL schemas for
competing last-place and overlapping-booking races. The browser test
`node tests/volunteers_browser.cjs` exercises citizen/admin HTMX flows and mobile
layout with synthetic fixtures. No government volunteer-platform integration is
claimed; Kerala Sannadhasena inspired the registration fields.
