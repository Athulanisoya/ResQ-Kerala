"""Temporary offers hold capacity without becoming arrivals or double bookings."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from backend.tests.test_auth import api, synthetic_password_hash
from backend.models import User
from backend.models.communication import Notification
from backend.models.shelter import Shelter, ShelterUpdate
from backend.models.shelter_registration import ShelterRegistration
from backend.models.shelter_waitlist import ShelterWaitlist, ShelterWaitlistEvent
from backend.services.shelter_waitlist_service import process_waitlists


def create_shelter(api, **changes):
    response = api.client.post("/api/shelters", headers=api.headers("admin"), json={
        "name": "Synthetic waiting-list shelter", "location": "Aluva synthetic hall",
        "district": "Ernakulam", "capacity": 3, "occupied": 3, **changes})
    assert response.status_code == 201, response.text
    return response.json()


def payload(**changes):
    return {"party_size": 2, "origin_district": "ernakulam", "origin_locality": "Aluva station",
            "request_key": str(uuid4()), "contact": "Synthetic contact", **changes}


def join(api, shelter_id, data=None, headers=None):
    return api.client.post(f"/api/shelters/{shelter_id}/waitlist", headers=headers or api.headers("citizen"),
                           json=data or payload())


def other_citizen(api, suffix="two"):
    response = api.client.post("/api/auth/register", json={"full_name": "Synthetic waiting citizen " + suffix,
        "email": "wait-" + suffix + "@example.com", "password": "Synthetic-waiting-tests!2026"})
    assert response.status_code == 201, response.text
    return {"Authorization": "Bearer " + response.json()["access_token"]}


def tick(api, **options):
    with api.sessions() as db:
        result = process_waitlists(db, **options)
        db.commit()
        return result


def release_walkins(api, shelter_id, occupied=0):
    current = api.client.get(f"/api/shelters/{shelter_id}", headers=api.headers("citizen")).json()
    response = api.client.patch(f"/api/shelters/{shelter_id}", headers=api.headers("admin"), json={
        "capacity": current["capacity"], "occupied": occupied, "expected_version": current["version"],
        "status": "OPEN", "note": "Synthetic reception released walk-in spaces"})
    assert response.status_code == 200, response.text


def act(api, row, action, headers=None, **changes):
    return api.client.post(f"/api/shelter-waitlist/{row['id']}/{action}", headers=headers or api.headers("citizen"),
                           json={"expected_version": row["version"], **changes})


def test_wait_then_offer_accept_reserves_once_and_only_reception_confirms_arrival(api):
    shelter = create_shelter(api)
    data = payload()
    queued = join(api, shelter["id"], data)
    assert queued.status_code == 201, queued.text
    row = queued.json()
    assert row["status"] == "WAITING" and row["shelter"]["occupied"] == 3
    assert row["groups_ahead"] == 0 and "2 spaces together" in row["skip_reason"]
    assert join(api, shelter["id"], data).json()["id"] == row["id"]
    release_walkins(api, shelter["id"])
    counts = tick(api)
    assert counts["offered"] == 1
    offered = api.client.get("/api/shelter-waitlist", headers=api.headers("citizen")).json()[0]
    assert offered["status"] == "OFFERED" and offered["shelter"]["occupied"] == 2
    assert offered["offer_expires_at"] and offered["registration_id"] is None
    accepted = act(api, offered, "accept")
    assert accepted.status_code == 200, accepted.text
    accepted = accepted.json()
    assert accepted["status"] == "ACCEPTED" and accepted["shelter"]["occupied"] == 2
    assert act(api, offered, "accept").json()["registration_id"] == accepted["registration_id"]
    with api.sessions() as db:
        registration = db.get(ShelterRegistration, accepted["registration_id"])
        assert registration.status == "RESERVED" and registration.party_size == 2
        assert db.scalar(select(func.count()).select_from(ShelterRegistration)) == 1
        auto = list(db.scalars(select(ShelterUpdate).where(ShelterUpdate.shelter_id == shelter["id"], ShelterUpdate.changed_by.is_(None))))
        assert len(auto) == 1
        assert db.scalar(select(func.count(Notification.id)).where(Notification.event_key.like("shelter-waitlist:%:offered:%"))) == 1
    assert tick(api)["expired"] == 0


def test_offer_expiry_releases_only_hold_and_notifies_once_then_rejoin_is_new_position(api):
    shelter = create_shelter(api, occupied=0)
    offered = join(api, shelter["id"]).json()
    assert offered["status"] == "OFFERED"
    deadline = datetime.fromisoformat(offered["offer_expires_at"])
    assert tick(api, now=deadline)["expired"] == 1
    assert tick(api, now=deadline + timedelta(hours=1))["expired"] == 0
    rows = api.client.get("/api/shelter-waitlist", headers=api.headers("citizen")).json()
    assert rows[0]["status"] == "EXPIRED" and rows[0]["shelter"]["occupied"] == 0
    assert act(api, offered, "accept").status_code == 409
    rejoined = join(api, shelter["id"]).json()
    assert rejoined["id"] > offered["id"]
    with api.sessions() as db:
        assert db.scalar(select(func.count(Notification.id)).where(Notification.event_key.like("%:expired:%"))) == 1


def test_cancel_waiting_and_offered_release_once_and_retry_does_not_reactivate(api):
    shelter = create_shelter(api)
    waiting = join(api, shelter["id"]).json()
    result = act(api, waiting, "cancel")
    assert result.status_code == 200 and result.json()["shelter"]["occupied"] == 3
    assert act(api, waiting, "cancel").status_code == 200
    release_walkins(api, shelter["id"])
    offered = join(api, shelter["id"]).json()
    assert offered["status"] == "OFFERED"
    cancelled = act(api, offered, "cancel")
    assert cancelled.status_code == 200 and cancelled.json()["shelter"]["occupied"] == 0
    assert act(api, offered, "cancel").json()["shelter"]["occupied"] == 0
    assert act(api, offered, "accept").status_code == 409


def test_fifo_fitting_groups_get_offers_without_splitting_older_large_group(api):
    shelter = create_shelter(api, capacity=4, occupied=4)
    oldest = join(api, shelter["id"], payload(party_size=3)).json()
    second_user = other_citizen(api)
    second = join(api, shelter["id"], payload(party_size=2), second_user).json()
    third_user = other_citizen(api, "three")
    third = join(api, shelter["id"], payload(party_size=1), third_user).json()
    release_walkins(api, shelter["id"], occupied=2)
    assert tick(api)["offered"] == 1
    with api.sessions() as db:
        assert db.get(ShelterWaitlist, oldest["id"]).status == "WAITING"
        assert "3 spaces together" in db.get(ShelterWaitlist, oldest["id"]).skip_reason
        assert db.get(ShelterWaitlist, second["id"]).status == "OFFERED"
        assert db.get(ShelterWaitlist, third["id"]).status == "WAITING"
        assert db.get(Shelter, shelter["id"]).occupied == 4


def test_new_direct_booking_cannot_jump_an_eligible_waiting_group(api):
    shelter = create_shelter(api)
    waiting = join(api, shelter["id"]).json()
    newcomer = other_citizen(api)
    release_walkins(api, shelter["id"])
    response = api.client.post(f"/api/shelters/{shelter['id']}/registrations", headers=newcomer,
                               json=payload(party_size=2))
    assert response.status_code == 409, response.text
    with api.sessions() as db:
        assert db.get(ShelterWaitlist, waiting["id"]).status == "OFFERED"
        assert db.get(Shelter, shelter["id"]).occupied == 2
    # The queued owner must explicitly accept instead of registering again.
    response = api.client.post(f"/api/shelters/{shelter['id']}/registrations", headers=api.headers("citizen"), json=payload())
    assert response.status_code == 409


def test_offer_holds_are_protected_from_manual_capacity_reduction(api):
    shelter = create_shelter(api, occupied=0)
    offered = join(api, shelter["id"]).json()
    response = api.client.patch(f"/api/shelters/{shelter['id']}", headers=api.headers("admin"), json={
        "capacity": 3, "occupied": 1, "expected_version": offered["shelter"]["version"], "note": "Synthetic invalid count"})
    assert response.status_code == 409


def test_closed_shelter_cancels_offer_releases_hold_and_pauses_waiting(api):
    shelter = create_shelter(api, occupied=0)
    offered = join(api, shelter["id"]).json()
    second = join(api, shelter["id"], headers=other_citizen(api)).json()
    with api.sessions() as db:
        db.get(Shelter, shelter["id"]).status = "CLOSED"; db.commit()
    assert act(api, offered, "accept").status_code == 409
    with api.sessions() as db:
        assert db.get(ShelterWaitlist, offered["id"]).status == "CANCELLED"
        assert db.get(ShelterWaitlist, second["id"]).status == "WAITING"
        assert "closed" in db.get(ShelterWaitlist, second["id"]).skip_reason
        assert db.get(Shelter, shelter["id"]).occupied == 0
        assert db.get(Shelter, shelter["id"]).status == "CLOSED"


def test_private_queue_and_actions_do_not_expose_other_citizens(api):
    shelter = create_shelter(api, occupied=0)
    row = join(api, shelter["id"]).json()
    other = other_citizen(api)
    assert api.client.get("/api/shelter-waitlist", headers=other).json() == []
    assert api.client.get(f"/api/shelters/{shelter['id']}/waitlist", headers=other).json() == []
    assert act(api, row, "accept", other).status_code == 404
    assert act(api, row, "cancel", other).status_code == 404
    assert api.client.get(f"/api/shelters/{shelter['id']}/waitlist", headers=api.headers("response_team")).status_code == 403
    assert act(api, row, "accept", api.headers("admin")).status_code == 403
    assert act(api, row, "cancel", api.headers("admin")).status_code == 200
    assert join(api, shelter["id"], headers=api.headers("admin")).status_code == 403


def test_inactive_citizen_offer_is_released_without_notifying_inactive_account(api):
    shelter = create_shelter(api, occupied=0)
    row = join(api, shelter["id"]).json()
    with api.sessions() as db:
        db.get(User, row["citizen_id"]).active = False; db.commit()
    assert tick(api)["cancelled"] == 1
    with api.sessions() as db:
        assert db.get(Shelter, shelter["id"]).occupied == 0


def test_accepted_registration_and_arrival_are_never_expired_by_offer_worker(api):
    shelter = create_shelter(api, occupied=0)
    offered = join(api, shelter["id"]).json()
    accepted = act(api, offered, "accept").json()
    response = api.client.patch(f"/api/shelter-registrations/{accepted['registration_id']}/status",
        headers=api.headers("admin"), json={"status": "ARRIVED", "expected_version": 1})
    assert response.status_code == 200
    assert tick(api, now=datetime.now(timezone.utc) + timedelta(days=2))["expired"] == 0
    with api.sessions() as db:
        assert db.get(ShelterRegistration, accepted["registration_id"]).status == "ARRIVED"
        assert db.get(Shelter, shelter["id"]).occupied == 2


@pytest.mark.parametrize("change", [{"party_size": 0}, {"party_size": True}, {"party_size": 1001},
    {"origin_district": "invented"}, {"origin_locality": " "}, {"origin_latitude": 9}, {"request_key": "invalid"}])
def test_invalid_queue_data_never_takes_spaces(api, change):
    shelter = create_shelter(api, occupied=0)
    assert join(api, shelter["id"], payload(**change)).status_code == 422
    with api.sessions() as db:
        assert db.get(Shelter, shelter["id"]).occupied == 0


def test_worker_retries_do_not_duplicate_events_notifications_or_holds(api):
    shelter = create_shelter(api)
    row = join(api, shelter["id"]).json()
    release_walkins(api, shelter["id"])
    assert tick(api)["offered"] == 1
    assert tick(api)["offered"] == 0
    with api.sessions() as db:
        assert db.get(Shelter, shelter["id"]).occupied == 2
        assert db.scalar(select(func.count()).select_from(ShelterWaitlistEvent)) == 2
        assert db.scalar(select(func.count(Notification.id)).where(Notification.event_key.like("shelter-waitlist:%"))) == 1
