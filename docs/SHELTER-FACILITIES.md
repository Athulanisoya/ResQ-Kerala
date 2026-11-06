# Structured shelter facilities

Shelter Search now offers five AND-combined filters: wheelchair access,
accessible toilets, medical support, charging facilities and pets allowed.
Only explicit staff-recorded YES values confirmed within 30 days match. NO,
UNKNOWN, missing, future-invalid and stale confirmations do not match. The
same parameters persist in live polling and combine with location, distance
and available-capacity searches before result limits are applied.

Administrators and the existing designated Shelter team use **Update facility
details**. The separate form requires all five YES/NO/UNKNOWN answers, a note,
confirmation checkbox and current facility version. Concurrent changes return
409. Confirmation records the staff actor, timestamp, version and a snapshot.
Existing free-text facilities are preserved and never interpreted as verified
structured facts. Existing shelters start UNKNOWN; the new tables are additive.

Facility confirmation has a separate timestamp and version from capacity.
Neither bookings, occupancy changes nor page polling reconfirm facilities.
Facility changes do not change capacity, reservations or capacity confirmation.
Public cards show each recorded answer, confirmation time and current/stale/
unknown state alongside the contact details. The assistant receives and displays
the same recorded evidence with its timestamp. Contact reception to confirm
current suitability and support; a record is not a guarantee of services.

API: PATCH `/api/shelters/{id}/facilities`, GET `/api/shelters?facility=charging`
(repeat `facility` for multiple requirements). Tests cover permissions, versions,
validation, stale/unknown exclusion, timestamps, polling and browser layouts.
