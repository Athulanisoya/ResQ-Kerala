# Private family safety

All account roles can use **More services → Family safety**. There is no
administrator access override, public directory, automatic location collection
or automatic link to private shelter registrations.

An owner creates a circle and requests an invitation using a known existing
account email. The API always returns the same acknowledgement for eligible,
unknown and inactive addresses. An eligible recipient sees an in-app invitation
and explicitly accepts or declines. Invitations expire after seven days; owners
can revoke pending requests. Each circle allows twenty members and twenty
invitation requests per day; a user may own five active circles. No SMTP service
is required and no email is sent. An account created after an invitation request
cannot claim that old request.

Members share their own status separately with each circle: Unknown, I am safe,
or Please contact me. Optional location text and a public recorded shelter are
blank by default. Sharing requires consent each time. Existing check-ins that
predate a viewer joining are hidden. Self-report timestamps are visible; after
24 hours status becomes Unknown and location/shelter details are hidden until
the person reconfirms. A check-in is not an incident report or rescue request.

Withdraw clears one's shared details. Leaving/removal denies subsequent reads
and clears the departed member's status and optional details. Owners end their
participation by closing the circle, ending all access and pending invitations.
This does not alter incident reports or shelter bookings. Circle row locks
serialize invitations, membership and sharing; versions reject stale actions.
Audit events contain action/time/actor only, with no location history. Retained
notifications contain generic notices, never check-in or location details.

Tests cover invitation consent, privacy across roles, expiration, stale status,
new-member visibility, version conflicts, revocation and data minimization.
PostgreSQL checks race invitation acceptance/revocation and check-in/leave in
disposable schemas. Browser checks exercise the real HTMX forms at 320/1440px.
