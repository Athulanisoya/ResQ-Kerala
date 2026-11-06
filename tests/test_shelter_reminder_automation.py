from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from backend.tests.test_auth import api, synthetic_password_hash
from backend.models import Role, Team, User
from backend.models.communication import Notification
from backend.models.shelter import Shelter
from backend.services.shelter_reminder_service import process_shelter_reminders


NOW = datetime(2026, 11, 5, 12, tzinfo=timezone.utc)


def fixture(api, *, age=45, staff=True, status="OPEN"):
    with api.sessions() as db:
        team = Team(name="Synthetic reminder reception", team_type="Shelter", status="AVAILABLE")
        db.add(team); db.flush()
        member = User(full_name="Synthetic reminder member", email=f"reminder-{uuid4().hex}@example.com",
                      role=Role.RESPONSE_TEAM, team_id=team.id, active=staff,
                      password_hash=db.get(User, api.users['citizen']).password_hash)
        db.add(member); db.flush()
        shelter = Shelter(name="Synthetic reminder shelter", location="Aluva", capacity=8, occupied=0,
                          team_id=team.id, status=status, updated_at=NOW,
                          capacity_confirmed_at=NOW-timedelta(minutes=age) if age is not None else None)
        db.add(shelter); db.commit()
        return shelter.id, member.id


def tick(api, when=NOW):
    with api.sessions() as db:
        result = process_shelter_reminders(db, now=when)
        db.commit()
        return result


def test_stale_staff_reminder_dedup_and_admin_escalation(api):
    shelter, member = fixture(api)
    result = tick(api)
    assert result["staff_notifications"] == 1 and result["admin_notifications"] == 0
    assert tick(api)["staff_notifications"] == 0
    # Escalation is independent of the regular reminder cadence.
    result = tick(api, NOW + timedelta(minutes=75))
    assert result["admin_notifications"] == 1
    assert tick(api, NOW + timedelta(minutes=76))["admin_notifications"] == 0
    with api.sessions() as db:
        messages = list(db.scalars(select(Notification)))
        assert all(row.incident_id is None and row.target_url.startswith('/shelters?') for row in messages)
        assert any(row.user_id == member for row in messages)
        row = db.get(Shelter, shelter)
        assert row.occupied == 0 and row.version == 1 and row.updated_at.replace(tzinfo=timezone.utc) == NOW


@pytest.mark.parametrize("age,staff,status,expected", [(0,True,"OPEN",0),(45,True,"CLOSED",0),
    (None,True,"OPEN",1),(45,False,"OPEN",1),(121,True,"OPEN",1)])
def test_fresh_closed_unknown_and_unstaffed_shelters(api, age, staff, status, expected):
    fixture(api, age=age, staff=staff, status=status)
    assert tick(api)["admin_notifications"] == expected


def test_reservation_does_not_confirm_capacity_and_explicit_capacity_edit_does(api):
    shelter, member = fixture(api)
    result = api.client.post(f'/api/shelters/{shelter}/registrations', headers=api.headers('citizen'), json={
        "party_size":1,"origin_district":"ernakulam","origin_locality":"Aluva","request_key":str(uuid4())})
    assert result.status_code == 201, result.text
    confirmed = result.json()['shelter']['capacity_confirmed_at']
    assert datetime.fromisoformat(confirmed).replace(tzinfo=timezone.utc) == NOW-timedelta(minutes=45)
    assert tick(api)["staff_notifications"] == 1
    row = api.client.get(f'/api/shelters/{shelter}',headers=api.headers('admin')).json()
    saved = api.client.patch(f'/api/shelters/{shelter}',headers=api.headers('admin'), json={
        "capacity":8,"occupied":1,"expected_version":row['version'],"note":"Synthetic head count confirmed"})
    assert saved.status_code == 200, saved.text
    with api.sessions() as db:
        # Use the returned confirmation's real clock for the next deterministic check.
        when = db.get(Shelter,shelter).capacity_confirmed_at.replace(tzinfo=timezone.utc)
    assert tick(api, when)["staff_notifications"] == 0
