"""Private reservations reserve/release real capacity without impersonating arrivals."""
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from backend.tests.test_auth import api, synthetic_password_hash
from backend.models import Role, Team, User
from backend.models.shelter import Shelter, ShelterUpdate
from backend.models.shelter_registration import ShelterRegistration, ShelterRegistrationEvent


def create_shelter(api, **changes):
    response = api.client.post("/api/shelters", headers=api.headers("admin"), json={
        "name": "Synthetic registration shelter", "location": "Aluva school hall", "capacity": 4,
        "occupied": 1, "district": "Ernakulam", "locality": "Aluva", **changes})
    assert response.status_code == 201, response.text
    return response.json()


def payload(**changes):
    return {"party_size": 3, "origin_district": "ernakulam", "origin_locality": "Aluva railway station",
            "contact": "Synthetic contact", "note": "Synthetic step-free access request",
            "request_key": str(uuid4()), **changes}


def reserve(api, shelter_id, data=None, headers=None):
    return api.client.post(f"/api/shelters/{shelter_id}/registrations", json=data or payload(),
                           headers=headers or api.headers("citizen"))


def status(api, registration, target, *, role="admin", **changes):
    return api.client.patch(f"/api/shelter-registrations/{registration['id']}/status", headers=api.headers(role),
                            json={"status": target, "expected_version": registration["version"], **changes})


def other_citizen(api):
    response = api.client.post("/api/auth/register", json={"full_name": "Other synthetic citizen",
        "email": "other-shelter@example.com", "password": "Synthetic-shelter-tests!2026"})
    assert response.status_code == 201
    return {"Authorization": "Bearer " + response.json()["access_token"]}


def test_reservation_updates_available_capacity_and_cancel_releases_once(api):
    shelter = create_shelter(api)
    data = payload()
    result = reserve(api, shelter["id"], data)
    assert result.status_code == 201, result.text
    row = result.json()
    assert row["status"] == "RESERVED" and row["origin_district"] == "Ernakulam"
    assert row["shelter"]["occupied"] == 4 and row["shelter"]["status"] == "FULL"
    assert row["shelter"]["available_capacity"] == 0 and row["shelter"]["version"] == 2
    assert "password_hash" not in str(row) and "request_fingerprint" not in row
    duplicate = reserve(api, shelter["id"], data)
    assert duplicate.status_code == 200 and duplicate.json()["id"] == row["id"]
    cancelled = status(api, row, "CANCELLED", role="citizen")
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["shelter"]["occupied"] == 1
    assert cancelled.json()["shelter"]["status"] == "OPEN"
    assert status(api, row, "CANCELLED", role="citizen").status_code == 200
    assert reserve(api, shelter["id"], data).json()["status"] == "CANCELLED"
    with api.sessions() as db:
        assert db.scalar(select(func.count()).select_from(ShelterRegistration)) == 1
        assert db.scalar(select(func.count()).select_from(ShelterRegistrationEvent)) == 2
        assert db.scalar(select(func.count()).select_from(ShelterUpdate).where(ShelterUpdate.shelter_id == shelter["id"])) == 3
        assert db.get(Shelter, shelter["id"]).occupied == 1


def test_only_reception_can_confirm_arrival_then_departure_releases_spaces(api):
    shelter = create_shelter(api)
    row = reserve(api, shelter["id"]).json()
    assert status(api, row, "ARRIVED", role="citizen").status_code == 403
    arrived = status(api, row, "ARRIVED", note="Synthetic reception confirmation")
    assert arrived.status_code == 200, arrived.text
    assert arrived.json()["status"] == "ARRIVED" and arrived.json()["shelter"]["occupied"] == 4
    assert arrived.json()["shelter"]["version"] == 2
    assert status(api, arrived.json(), "CANCELLED", role="citizen").status_code == 409
    departed = status(api, arrived.json(), "DEPARTED")
    assert departed.status_code == 200 and departed.json()["shelter"]["occupied"] == 1
    assert [event["status"] for event in departed.json()["history"]] == ["RESERVED", "ARRIVED", "DEPARTED"]
    # An old arrival request cannot reopen a departed registration.
    assert status(api, row, "ARRIVED", note="Synthetic reception confirmation").status_code == 409


def test_closed_full_and_insufficient_space_do_not_change_counts(api):
    shelter = create_shelter(api, capacity=2, occupied=1)
    assert reserve(api, shelter["id"], payload(party_size=2)).status_code == 409
    with api.sessions() as db:
        row = db.get(Shelter, shelter["id"])
        row.status = "CLOSED"; db.commit()
    assert reserve(api, shelter["id"], payload(party_size=1)).status_code == 409
    with api.sessions() as db:
        assert db.get(Shelter, shelter["id"]).occupied == 1
        assert db.scalar(select(func.count()).select_from(ShelterRegistration)) == 0


def test_private_rosters_and_other_citizen_transition_are_denied(api):
    shelter = create_shelter(api)
    row = reserve(api, shelter["id"]).json()
    other = other_citizen(api)
    assert api.client.get(f"/api/shelters/{shelter['id']}/registrations", headers=other).json() == []
    assert api.client.get("/api/shelter-registrations", headers=other).json() == []
    assert api.client.patch(f"/api/shelter-registrations/{row['id']}/status", headers=other,
        json={"status": "CANCELLED", "expected_version": 1}).status_code == 404
    denied = api.client.get(f"/api/shelters/{shelter['id']}/registrations", headers=api.headers("response_team"))
    assert denied.status_code == 403 and "Synthetic contact" not in denied.text
    assert status(api, row, "ARRIVED", role="response_team").status_code == 403
    assert api.client.get(f"/api/shelters/{shelter['id']}/registrations").status_code == 401
    own = api.client.get("/api/shelter-registrations", headers=api.headers("citizen"))
    assert own.status_code == 200 and own.json()[0]["id"] == row["id"]
    assert own.json()[0]["shelter"]["status"] == "FULL"


def test_designated_shelter_team_can_receive_but_other_shelter_team_cannot(api):
    with api.sessions() as db:
        team = Team(name="Synthetic reception", team_type="Shelter")
        other = Team(name="Other synthetic reception", team_type="Shelter")
        db.add_all([team, other]); db.flush()
        db.get(User, api.users["response_team"]).team_id = team.id
        db.commit(); team_id, other_id = team.id, other.id
    shelter = create_shelter(api, team_id=team_id)
    row = reserve(api, shelter["id"]).json()
    assert api.client.get(f"/api/shelters/{shelter['id']}/registrations", headers=api.headers("response_team")).status_code == 200
    assert status(api, row, "ARRIVED", role="response_team").status_code == 200
    with api.sessions() as db:
        db.get(User, api.users["response_team"]).team_id = other_id; db.commit()
    assert api.client.get(f"/api/shelters/{shelter['id']}/registrations", headers=api.headers("response_team")).status_code == 403


def test_request_key_reuse_changed_details_and_second_active_registration_are_rejected(api):
    shelter = create_shelter(api, capacity=30)
    data = payload()
    row = reserve(api, shelter["id"], data).json()
    assert reserve(api, shelter["id"], {**data, "party_size": 2}).status_code == 409
    assert reserve(api, shelter["id"], payload()).status_code == 409
    assert status(api, row, "CANCELLED", role="citizen").status_code == 200
    assert reserve(api, shelter["id"], payload()).status_code == 201


@pytest.mark.parametrize("change", [{"party_size": 0}, {"party_size": True}, {"party_size": 1001},
    {"origin_district": "invented-district"}, {"origin_locality": " "}, {"origin_latitude": 10.2},
    {"origin_latitude": 91, "origin_longitude": 76}, {"request_key": "invalid"}, {"citizen_id": 99}])
def test_invalid_registration_inputs_are_rejected(api, change):
    shelter = create_shelter(api)
    assert reserve(api, shelter["id"], payload(**change)).status_code == 422
    with api.sessions() as db:
        assert db.get(Shelter, shelter["id"]).occupied == 1


def test_capacity_editor_cannot_erase_reserved_places(api):
    shelter = create_shelter(api, capacity=20)
    row = reserve(api, shelter["id"], payload(party_size=4)).json()
    response = api.client.patch(f"/api/shelters/{shelter['id']}", headers=api.headers("admin"), json={
        "capacity": 20, "occupied": 3, "expected_version": 2, "note": "Synthetic bad reception count"})
    assert response.status_code == 409
    with api.sessions() as db:
        assert db.get(Shelter, shelter["id"]).occupied == 5
    assert status(api, row, "CANCELLED", role="citizen").status_code == 200


def test_cancelling_reservation_does_not_reopen_closed_shelter(api):
    shelter = create_shelter(api)
    row = reserve(api, shelter["id"]).json()
    with api.sessions() as db:
        db.get(Shelter, shelter["id"]).status = "CLOSED"; db.commit()
    result = status(api, row, "CANCELLED", role="citizen")
    assert result.status_code == 200 and result.json()["shelter"]["status"] == "CLOSED"
    assert result.json()["shelter"]["occupied"] == 1
