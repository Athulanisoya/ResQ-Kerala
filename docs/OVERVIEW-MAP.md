# Overview map and shelter registration

Every signed-in role sees **Kerala alerts & shelters** on Overview. The map uses
the same administrator-issued alerts as the alert list. It refreshes every 30
seconds while the page is visible; Refresh checks immediately.

## Explore alerts

- Red, orange and yellow are the highest **currently active** alert anywhere
  in a district. Green means no active alert in this application. It does not
  establish safety. Scheduled and expired alerts do not colour the map.
- Select a district to zoom in and read its exact alert coverage. A locality
  alert contributes to the district summary colour, but does not become a
  district-wide alert. District-wide alerts also apply to that district's
  locality markers.
- Locality centres appear from zoom level 9, with names visible from level 11.
  They are points, not invented locality boundaries or a flood-extent model.
  All catalog localities are selectable in the text alternative, including
  places without a sourced coordinate. Missing coordinates are explicit.
- Failed refreshes show unknown grey coverage and remove shelter pins. The
  interface does not substitute green when evidence is unavailable.

The map bundles Leaflet 1.9.4 and reference geography locally, so it needs no
map API key, external tile server or runtime geocoding. It covers 14 district
polygons and 82 sourced centres from the 100-place locality catalog. See
[geography provenance and licences](../data/map/README.md). Leaflet's BSD licence
is retained in `frontend/static/vendor/leaflet/LICENSE`. District shapes are
simplified reference data, not turn-by-turn travel guidance.

## Find and register for a shelter

Shelter pins use the shelter's recorded coordinates. Shelters without coordinates
remain in the text and shelter lists. Each record shows capacity, occupied or
reserved spaces, record update time, recent/stale/unknown status and contact.
Refreshing the page does not confirm the underlying capacity.

Selecting a locality sorts shelters from its approximate centre. **Use my
location** optionally asks the browser for a device position and sorts from
that point instead. Device coordinates stay in page memory and are discarded
on navigation. Distance is straight-line, not a route or an assurance of safe
travel. Users can register without granting browser location permission.

Citizens choose **Register to join** on a pin or shelter card. The form at
`/shelters/{id}/join` requires their current district/locality and group size.
An explored area can prefill the form; the citizen reviews it before submission.
Contact, support notes and explicitly entered coordinates are optional and
private to the citizen, administrators and designated Shelter team.

Submitting reserves spaces immediately. A database row lock serializes
reservations and ordinary capacity edits; the database and service enforce
capacity bounds and protect retry requests. Counts include both reservations
and present guests, so a reservation does not claim an arrival.

- **Reserved:** the citizen or reception can cancel and release the spaces.
- **Arrived:** an administrator or the designated Shelter team confirms arrival.
- **Departed:** reception records departure and releases the spaces.

Transitions retain audit events and require the current registration version.
Existing reservations remain accessible when the shelter becomes full or closed.
Citizens use **Shelters → My shelter registrations** for their private history;
authorized reception uses **Manage registrations** for a shelter's private roster.
Other citizens and unrelated teams cannot read it. Normal occupancy edits cannot
reduce the combined count below active registrations.

## Verification

Run the normal Python suite with `python -m pytest`. The opt-in PostgreSQL race
test, `tests/test_shelter_registration_postgres.py`, uses
`RESQ_TEST_POSTGRES_URL` and creates/removes a random test schema; it checks two
independent requests competing for the last spaces.

`tests/overview_map_browser.cjs` exercises real alert timing, all three roles,
zooming, shelter pins, registration and reception, privacy, failed-fetch states,
HTMX re-entry, and desktop/mobile layouts. It creates clearly labelled synthetic
local fixtures, releases its reservations and expires its alerts. Run it with
Playwright and Chrome available, `BASE_URL` pointing to the local app, and
`RESQ_DEMO_ACCOUNTS` pointing to the private demo-account file. The default target
is the Docker app at port 8014.
