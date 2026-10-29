"""
Vidya Week 4 tests.

These tests check:
1. Citizen visibility after every rescue status change.
2. Rejection of skipped workflow stages.
3. Task acceptance permissions.
4. Rejection of busy-team assignment.
5. Rescue-to-relief handoff.
6. Relief delivery retries and completion.
7. Incident privacy.

These tests use the existing isolated test database fixtures.
"""

# pytest runs the tests and supports testing several input values.
import pytest

# select builds database queries.
from sqlalchemy import select

# Import the existing database and password fixtures.
# These imports also make the fixtures available in this test module.
from .test_auth import api, synthetic_password_hash

# Import existing workflow setup and API helper functions.
from .test_workflows import workflow, submit, review, assign

# Import database models used to inspect saved values.
from backend.models import Incident, IncidentStatusHistory, Team

# Import the relief database models.
from backend.models.relief import (
    Inventory,
    ReliefRequest,
    Distribution,
)

# Generate a unique retry key for each new delivery.
from uuid import uuid4


# ------------------------------------------------------------
# TEST SETUP
# Reuse the existing workflow fixture.
#
# It already provides:
# - citizen
# - admin
# - assigned Rescue team member: response_team
# - Relief team member: other_team
# - another citizen: other_citizen
# ------------------------------------------------------------

@pytest.fixture
def services(workflow):

    # The current Week 4 tests need the existing workflow setup.
    return workflow


# ------------------------------------------------------------
# Create, verify and assign one incident.
# ------------------------------------------------------------

def assigned(api):

    # Create the report as the citizen.
    response = submit(api)
    assert response.status_code == 201, response.text

    # Store the new incident ID.
    incident_id = response.json()["id"]

    # Verify the report as admin.
    response = review(api, incident_id)
    assert response.status_code == 200, response.text

    # Assign the Rescue team as admin.
    response = assign(api, incident_id)
    assert response.status_code == 200, response.text

    # Give the incident ID back to the calling test.
    return incident_id


# ------------------------------------------------------------
# Accept a task as the selected account.
# ------------------------------------------------------------

def accept(api, incident_id, role="response_team"):

    return api.client.post(
        f"/api/teams/incidents/{incident_id}/accept",
        headers=api.headers(role),
    )


# ------------------------------------------------------------
# Update task progress as the selected account.
# ------------------------------------------------------------

def progress(
    api,
    incident_id,
    status,
    role="response_team",
):

    return api.client.patch(
        f"/api/incidents/{incident_id}/progress",
        headers=api.headers(role),
        json={
            "status": status,
            "note": "Week 4 automated test progress update",
        },
    )


# ------------------------------------------------------------
# Accept a task and move it to IN_PROGRESS.
# ------------------------------------------------------------

def start(api, incident_id, role="response_team"):

    # Accept the assignment.
    response = accept(api, incident_id, role)
    assert response.status_code == 200, response.text

    # Start travelling, then start work.
    for status in ["EN_ROUTE", "IN_PROGRESS"]:

        response = progress(
            api,
            incident_id,
            status,
            role,
        )

        assert response.status_code == 200, response.text


# ------------------------------------------------------------
# Create a citizen relief request.
# ------------------------------------------------------------

def relief_request(
    api,
    incident_id,
    quantity=10,
    role="citizen",
    item="FOOD",
):

    return api.client.post(
        f"/api/relief/incidents/{incident_id}/requests",
        headers=api.headers(role),
        json={
            "item": item,
            "quantity": quantity,
        },
    )


# ------------------------------------------------------------
# Hand over the completed rescue case to the Relief team.
# ------------------------------------------------------------

def handoff(api, incident_id, role="admin"):

    return api.client.post(
        f"/api/incidents/{incident_id}/relief-handoff",
        headers=api.headers(role),
        json={
            "team_id": api.other_team_id,
            "note": "Rescue completed and relief supplies required",
        },
    )


# ------------------------------------------------------------
# Prepare an incident for relief delivery testing.
# ------------------------------------------------------------

def setup_relief(api):

    # Create, verify and assign the rescue incident.
    incident_id = assigned(api)

    # Request ten FOOD units.
    request_response = relief_request(api, incident_id)
    assert request_response.status_code == 201, request_response.text

    # Store the relief request ID.
    request_id = request_response.json()["id"]

    # Accept the rescue task and start rescue work.
    start(api, incident_id)

    # Complete rescue.
    response = progress(
        api,
        incident_id,
        "RESCUE_COMPLETED",
    )
    assert response.status_code == 200, response.text

    # Admin hands the incident to the Relief team.
    response = handoff(api, incident_id)
    assert response.status_code == 200, response.text

    # The Relief team accepts, travels and starts work.
    start(api, incident_id, "other_team")

    # Admin creates twenty FOOD units of stock.
    stock_response = api.client.post(
        "/api/relief/inventory",
        headers=api.headers("admin"),
        json={
            "item": "FOOD",
            "quantity": 20,
        },
    )

    assert stock_response.status_code == 201, stock_response.text

    # Store the stock record ID.
    stock_id = stock_response.json()["id"]

    # Return the three different record IDs.
    return incident_id, request_id, stock_id


# ------------------------------------------------------------
# Record a relief delivery.
# ------------------------------------------------------------

def deliver(
    api,
    request_id,
    quantity,
    key=None,
    role="other_team",
):

    # Generate a new UUID unless the test supplies a retry key.
    delivery_key = key if key is not None else str(uuid4())

    return api.client.post(
        f"/api/relief/requests/{request_id}/distributions",
        headers=api.headers(role),
        json={
            "quantity": quantity,
            "idempotency_key": delivery_key,
        },
    )


# ------------------------------------------------------------
# HELPER 1
# Check that the original citizen can still view the incident.
# ------------------------------------------------------------

def citizen_view(api, incident_id, expected_status):

    # Get the original citizen's authentication header.
    headers = api.headers("citizen")

    # Build the URL using the actual incident ID.
    path = f"/api/incidents/{incident_id}"

    # Read incident details as the original citizen.
    detail = api.client.get(path, headers=headers)

    # The original citizen must be allowed to read the incident.
    # If this fails, show the server response in the test output.
    assert detail.status_code == 200, detail.text

    # The incident must still belong to its original citizen.
    assert detail.json()["user_id"] == api.users["citizen"]

    # The incident detail must show the latest status.
    assert detail.json()["status"] == expected_status

    # Read the citizen's incident list again.
    listing = api.client.get(
        "/api/incidents/",
        headers=headers,
    )

    # The list request must succeed.
    assert listing.status_code == 200, listing.text

    # Find this incident in the returned list.
    # If it is missing, row becomes None.
    row = next(
        (
            report
            for report in listing.json()
            if report["id"] == incident_id
        ),
        None,
    )

    # The incident must remain in the citizen's list.
    assert row is not None

    # Its list entry must show the latest status.
    assert row["status"] == expected_status

    # Read the dedicated status endpoint.
    status_response = api.client.get(
        path + "/status",
        headers=headers,
    )

    # The owner must be allowed to read its status.
    assert status_response.status_code == 200, status_response.text

    # Check the incident ID and current status.
    assert status_response.json() == {
        "incident_id": incident_id,
        "status": expected_status,
    }

    # Read the incident timeline.
    history_response = api.client.get(
        path + "/history",
        headers=headers,
    )

    # The owner must retain access to the timeline.
    assert history_response.status_code == 200, history_response.text

    # The final timeline entry must match the current status.
    assert history_response.json()[-1]["status"] == expected_status


# ------------------------------------------------------------
# HELPER 2
# Read saved values before and after a rejected action.
# ------------------------------------------------------------

def saved_state(api, incident_id):

    # Open a fresh session connected to the isolated test database.
    with api.sessions() as db:

        # Read the incident using its primary key.
        incident = db.get(Incident, incident_id)

        # Read this incident's history in insertion order.
        history_rows = db.scalars(
            select(IncidentStatusHistory)
            .where(
                IncidentStatusHistory.incident_id == incident_id
            )
            .order_by(IncidentStatusHistory.id)
        ).all()

        # Read all test teams in a stable order.
        teams = db.scalars(
            select(Team).order_by(Team.id)
        ).all()

        # Return the important values for comparison.
        # A rejected action should leave these values unchanged.
        return (
            incident.user_id,
            incident.status,
            incident.assigned_team_id,
            [
                (row.id, row.status, row.note)
                for row in history_rows
            ],
            [
                (team.id, team.status)
                for team in teams
            ],
        )


# ------------------------------------------------------------
# TEST 1
# The original citizen must see every rescue stage.
# ------------------------------------------------------------

def test_owner_sees_every_rescue_stage(services):

    # Use the synthetic accounts, teams and isolated database.
    api = services

    # Submit an incident as the citizen.
    created = submit(api)

    # Incident creation should return HTTP 201.
    assert created.status_code == 201, created.text

    # Store the ID returned by the API.
    incident_id = created.json()["id"]

    # Check citizen access immediately after creation.
    citizen_view(api, incident_id, "SUBMITTED")

    # Verify the incident as admin.
    assert review(api, incident_id).status_code == 200

    # Check citizen access after verification.
    citizen_view(api, incident_id, "VERIFIED")

    # Assign the Rescue team as admin.
    assert assign(api, incident_id).status_code == 200

    # Check citizen access after assignment.
    citizen_view(api, incident_id, "ASSIGNED")

    # Accept the task as the assigned Rescue team.
    assert accept(api, incident_id).status_code == 200

    # Check citizen access after task acceptance.
    citizen_view(api, incident_id, "ACCEPTED")

    # Move through the remaining rescue stages in order.
    for status in [
        "EN_ROUTE",
        "IN_PROGRESS",
        "RESCUE_COMPLETED",
    ]:

        # The assigned team's progress update should succeed.
        response = progress(api, incident_id, status)
        assert response.status_code == 200, response.text

        # The original citizen must still see the updated incident.
        citizen_view(api, incident_id, status)

    # Read the completed rescue history as the citizen.
    history_response = api.client.get(
        f"/api/incidents/{incident_id}/history",
        headers=api.headers("citizen"),
    )

    # Check that reading history succeeded.
    assert history_response.status_code == 200

    # Extract only the statuses from the history records.
    actual_statuses = [
        row["status"]
        for row in history_response.json()
    ]

    # The saved history must follow the expected rescue order.
    assert actual_statuses == [
        "SUBMITTED",
        "VERIFIED",
        "ASSIGNED",
        "ACCEPTED",
        "EN_ROUTE",
        "IN_PROGRESS",
        "RESCUE_COMPLETED",
    ]


# ------------------------------------------------------------
# TEST 2
# Reject attempts to skip acceptance and other required stages.
# pytest runs this test three times.
# ------------------------------------------------------------

@pytest.mark.parametrize(
    "target",
    [
        "IN_PROGRESS",
        "RESCUE_COMPLETED",
        "RESOLVED",
    ],
)
def test_skipped_progress_keeps_records_unchanged(
    services,
    target,
):

    # Get a fresh isolated setup for this test.
    api = services

    # Create, verify and assign an incident.
    # Its current status is ASSIGNED.
    incident_id = assigned(api)

    # Record saved values before attempting the invalid update.
    before = saved_state(api, incident_id)

    # Try to jump directly to the target status.
    response = progress(api, incident_id, target)

    # HTTP 409 means this action conflicts with the workflow.
    assert response.status_code == 409, response.text

    # The rejected update must not change the checked records.
    assert saved_state(api, incident_id) == before


# ------------------------------------------------------------
# TEST 3
# Only the assigned response team can accept its task.
# pytest runs this test for three different actors.
# ------------------------------------------------------------

@pytest.mark.parametrize(
    "role",
    [
        "citizen",
        "admin",
        "other_team",
    ],
)
def test_acceptance_requires_assigned_team(services, role):

    # Get the isolated accounts and teams.
    api = services

    # Prepare an incident assigned to the Rescue team.
    incident_id = assigned(api)

    # Record values before the forbidden acceptance attempt.
    before = saved_state(api, incident_id)

    # Attempt acceptance using the selected actor's account.
    response = accept(api, incident_id, role)

    # The actor is not permitted to accept this team's task.
    assert response.status_code == 403, response.text

    # A rejected acceptance must not change saved values.
    assert saved_state(api, incident_id) == before


# ------------------------------------------------------------
# TEST 4
# A busy Rescue team cannot receive a second incident.
# ------------------------------------------------------------

def test_busy_team_cannot_receive_second_incident(services):

    # Get the isolated service setup.
    api = services

    # Assign the Rescue team to the first incident.
    # The team is now busy.
    first_id = assigned(api)

    # Create another citizen incident.
    second_response = submit(api)
    assert second_response.status_code == 201

    # Store the second incident's ID.
    second_id = second_response.json()["id"]

    # Verify the second incident so it is eligible for assignment.
    assert review(api, second_id).status_code == 200

    # Save the first incident and team values.
    first_before = saved_state(api, first_id)

    # Save the second incident and team values.
    second_before = saved_state(api, second_id)

    # Try assigning the same busy Rescue team to the second incident.
    response = assign(api, second_id)

    # The API should reject the busy-team assignment.
    assert response.status_code == 409, response.text

    # The first case must keep its existing assignment.
    assert saved_state(api, first_id) == first_before

    # The second case must remain verified and unassigned.
    assert saved_state(api, second_id) == second_before


# ------------------------------------------------------------
# TEST 5
# Handoff must preserve ownership and update team availability.
# ------------------------------------------------------------

def test_handoff_preserves_owner_and_releases_rescue_team(
    services,
):

    # Get the isolated service setup.
    api = services

    # Prepare an assigned rescue incident.
    incident_id = assigned(api)

    # Create a request for ten FOOD units as the citizen.
    request_response = relief_request(api, incident_id)
    assert request_response.status_code == 201

    # Accept the rescue task and move it through travel
    # to IN_PROGRESS.
    start(api, incident_id)

    # Complete the rescue work.
    completed = progress(
        api,
        incident_id,
        "RESCUE_COMPLETED",
    )
    assert completed.status_code == 200

    # Hand over the incident to the Relief team as admin.
    handoff_response = handoff(api, incident_id)
    assert handoff_response.status_code == 200

    # The incident returns to ASSIGNED for the new Relief task.
    # Its original citizen must still have access.
    citizen_view(api, incident_id, "ASSIGNED")

    # Read the saved handoff results.
    with api.sessions() as db:

        # The incident must now point to the Relief team.
        incident = db.get(Incident, incident_id)
        assert incident.assigned_team_id == api.other_team_id

        # The former Rescue team must be available again.
        rescue_team = db.get(Team, api.team_id)
        assert rescue_team.available is True

        # The new Relief team must be busy.
        relief_team = db.get(Team, api.other_team_id)
        assert relief_team.available is False

    # Save the successful handoff result.
    before = saved_state(api, incident_id)

    # The default progress actor is the former Rescue team.
    # That team must no longer update this incident.
    old_team_attempt = progress(
        api,
        incident_id,
        "EN_ROUTE",
    )

    # The former team should receive HTTP 403.
    assert old_team_attempt.status_code == 403

    # Its rejected update must not change saved values.
    assert saved_state(api, incident_id) == before


# ------------------------------------------------------------
# TEST 6
# Delivery retries must not deduct stock twice.
# Relief resolution requires all demand to be fulfilled.
# ------------------------------------------------------------

def test_relief_retry_and_resolution_keep_citizen_access(
    services,
):

    # Get the isolated service setup.
    api = services

    # Prepare:
    # - ten FOOD units requested;
    # - twenty FOOD units in stock;
    # - Relief team working at IN_PROGRESS.
    incident_id, request_id, stock_id = setup_relief(api)

    # Identify one delivery using a valid UUID.
    # A fixed value is safe here because each test has a fresh DB.
    key = "7bb960d6-8cc0-4ead-b266-3b8bf084790d"

    # Deliver four units.
    first = deliver(api, request_id, 4, key)

    # The delivery should succeed.
    assert first.status_code == 200, first.text

    # Repeat exactly the same request with the same retry key.
    retry = deliver(api, request_id, 4, key)

    # The repeated request should return successfully.
    assert retry.status_code == 200, retry.text

    # It should return the original delivery result.
    assert retry.json() == first.json()

    # Inspect saved quantities after the retry.
    with api.sessions() as db:

        # Starting stock was twenty.
        # Only four units should have been deducted.
        inventory = db.get(Inventory, stock_id)
        assert inventory.quantity == 16

        # The request should show four fulfilled units.
        request = db.get(ReliefRequest, request_id)
        assert request.fulfilled == 4

    # Record incident, history and team values.
    before = saved_state(api, incident_id)

    # Try to resolve relief before supplying the remaining six.
    premature_resolution = progress(
        api,
        incident_id,
        "RESOLVED",
        "other_team",
    )

    # Resolution should be rejected while demand remains.
    assert premature_resolution.status_code == 409

    # The rejected resolution must not change checked values.
    assert saved_state(api, incident_id) == before

    # Supply the remaining six units.
    # The helper generates a new UUID when no key is passed.
    remaining_delivery = deliver(api, request_id, 6)
    assert remaining_delivery.status_code == 200

    # Now all ten requested units are fulfilled.
    resolution = progress(
        api,
        incident_id,
        "RESOLVED",
        "other_team",
    )

    # Relief resolution should now succeed.
    assert resolution.status_code == 200, resolution.text

    # The original citizen must still see the resolved incident.
    citizen_view(api, incident_id, "RESOLVED")

    # Check the final saved quantities.
    with api.sessions() as db:

        # Twenty starting units minus ten delivered leaves ten.
        inventory = db.get(Inventory, stock_id)
        assert inventory.quantity == 10

        # All ten requested units must be fulfilled.
        request = db.get(ReliefRequest, request_id)
        assert request.fulfilled == 10

        # There must be two deliveries: four units and six units.
        # Retrying the first delivery must not create a third row.
        deliveries = db.scalars(select(Distribution)).all()
        assert len(deliveries) == 2


# ------------------------------------------------------------
# TEST 7
# Another citizen and requests without login cannot read a case.
# pytest runs this test for three endpoints.
# ------------------------------------------------------------

@pytest.mark.parametrize(
    "suffix",
    [
        "",
        "/status",
        "/history",
    ],
)
def test_other_citizen_and_missing_token_cannot_read(
    services,
    suffix,
):

    # Get the isolated accounts, including another citizen.
    api = services

    # Prepare an incident owned by the original citizen.
    incident_id = assigned(api)

    # Build the detail, status or history endpoint.
    path = f"/api/incidents/{incident_id}{suffix}"

    # Save current incident, history and team values.
    before = saved_state(api, incident_id)

    # Attempt to read it using another citizen's valid token.
    other_citizen_response = api.client.get(
        path,
        headers=api.headers("other_citizen"),
    )

    # Another citizen does not own this report.
    assert other_citizen_response.status_code == 403

    # Attempt to read the same endpoint without any token.
    anonymous_response = api.client.get(path)

    # A request without authentication should receive HTTP 401.
    assert anonymous_response.status_code == 401

    # These denied reads must not change saved values.
    assert saved_state(api, incident_id) == before