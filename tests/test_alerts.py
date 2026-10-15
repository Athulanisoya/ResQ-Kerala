"""Isolated Week 2 alert lifecycle, permissions and geographic coverage tests."""
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["ALLOW_SQLITE_FOR_TESTS"] = "true"
os.environ["JWT_SECRET"] = "synthetic-alert-tests-only-secret-2026"

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.ai.location_extractor import LocationExtraction, extract_location, list_places
from backend.database.connection import Base, get_db
from backend.models import Role, TokenSession, User
from backend.models.alert import Alert
from backend.routers import alerts, auth
from backend.services.alert_service import match_alerts
from backend.utils.security import hash_password


PASSWORD = "Synthetic-alert-pass!2026"


@dataclass
class Harness:
    client: TestClient
    sessions: object
    users: dict
    tokens: dict = field(default_factory=dict)

    def headers(self, role="admin"):
        if role not in self.tokens:
            response = self.client.post("/api/auth/login", json={
                "email": f"{role}@example.com", "password": PASSWORD,
            })
            assert response.status_code == 200, response.text
            self.tokens[role] = response.json()["access_token"]
        return {"Authorization": f"Bearer {self.tokens[role]}"}

    def create(self, place_id, **changes):
        now = datetime.now(timezone.utc)
        payload = {
            "title": "Flood warning", "message": "Flood water is rising; follow local official instructions.",
            "level": "ORANGE", "place_id": place_id,
            "starts_at": (now - timedelta(hours=1)).isoformat(),
            "expires_at": (now + timedelta(hours=2)).isoformat(), **changes,
        }
        response = self.client.post("/api/alerts", json=payload, headers=self.headers())
        assert response.status_code == 201, response.text
        return response.json()


@pytest.fixture(scope="session")
def alert_password_hash():
    return hash_password(PASSWORD)


@pytest.fixture
def api(alert_password_hash):
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as db:
        users = [User(full_name=f"Test {role.value}", email=f"{role.value}@example.com",
                      password_hash=alert_password_hash, role=role) for role in Role]
        db.add_all(users)
        db.commit()
        ids = {user.role.value: user.id for user in users}

    app = FastAPI()
    app.include_router(auth.router)
    app.include_router(alerts.router)

    def override_database():
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = override_database
    try:
        with TestClient(app) as client:
            yield Harness(client, sessions, ids)
    finally:
        engine.dispose()


@pytest.fixture
def places():
    catalog = list_places()
    districts = [place for place in catalog if place.kind == "district"]
    for district in districts:
        localities = [place for place in catalog if place.kind == "locality" and place.district_id == district.id]
        if len(localities) >= 2:
            other = next(place for place in districts if place.id != district.id)
            return district, localities[0], localities[1], other
    pytest.fail("The Kerala place catalog needs a district with at least two localities.")


def test_alert_routes_require_login_and_admin_mutations(api, places):
    district, *_ = places
    for path in ("/api/alerts", "/api/alerts/places"):
        assert api.client.get(path).status_code == 401
    assert api.client.post("/api/alerts/match", json={"message": district.name}).status_code == 401
    for role in ("citizen", "response_team"):
        headers = api.headers(role)
        assert api.client.get("/api/alerts", headers=headers).status_code == 200
        assert api.client.get("/api/alerts/places", headers=headers).status_code == 200
        assert api.client.get("/api/alerts?include_inactive=true", headers=headers).status_code == 403
        payload = {"title": "Flood warning", "message": "Stay clear of flood water.", "level": "RED",
                   "place_id": district.id, "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}
        assert api.client.post("/api/alerts", json=payload, headers=headers).status_code == 403
        assert api.client.patch("/api/alerts/1", json={"title": "Changed warning"}, headers=headers).status_code == 403
        assert api.client.post("/api/alerts/1/expire", headers=headers).status_code == 403


def test_active_scheduled_expired_and_severity_order(api, places):
    district, *_ = places
    now = datetime.now(timezone.utc)
    yellow = api.create(district.id, level="YELLOW")
    red = api.create(district.id, level="RED")
    future = api.create(district.id, starts_at=(now + timedelta(hours=1)).isoformat())
    expired = api.create(district.id, starts_at=(now - timedelta(hours=3)).isoformat(), expires_at=(now - timedelta(hours=1)).isoformat())
    assert [yellow["status"], red["status"], future["status"], expired["status"]] == ["ACTIVE", "ACTIVE", "SCHEDULED", "EXPIRED"]
    active = api.client.get("/api/alerts", headers=api.headers("citizen")).json()
    assert [item["id"] for item in active] == [red["id"], yellow["id"]]
    all_alerts = api.client.get("/api/alerts?include_inactive=true", headers=api.headers()).json()
    assert {item["id"] for item in all_alerts} == {yellow["id"], red["id"], future["id"], expired["id"]}
    assert all(item["starts_at"].endswith("Z") for item in all_alerts)


def test_edit_changes_coverage_without_changing_creator_and_expire_is_final(api, places):
    district, locality, *_ = places
    alert = api.create(district.id)
    headers = api.headers()
    edited = api.client.patch(f"/api/alerts/{alert['id']}", headers=headers, json={
        "title": "Updated local warning", "place_id": locality.id, "level": "RED",
    })
    assert edited.status_code == 200, edited.text
    body = edited.json()
    assert (body["place_id"], body["place_name"], body["place_kind"], body["level"]) == (locality.id, locality.name, "locality", "RED")
    assert body["created_by_id"] == api.users["admin"] == alert["created_by_id"]
    assert body["created_at"] == alert["created_at"]
    expired = api.client.post(f"/api/alerts/{alert['id']}/expire", headers=headers)
    assert expired.status_code == 200 and expired.json()["status"] == "EXPIRED"
    again = api.client.post(f"/api/alerts/{alert['id']}/expire", headers=headers)
    assert again.json()["expired_at"] == expired.json()["expired_at"]
    assert api.client.patch(f"/api/alerts/{alert['id']}", headers=headers, json={"title": "Reissued warning"}).status_code == 409
    assert api.client.get("/api/alerts", headers=api.headers("citizen")).json() == []


@pytest.mark.parametrize("changes", [
    {"place_id": "unverified-user-location"}, {"level": "GREEN"}, {"created_by_id": 999},
    {"expires_at": "2020-01-01T00:00:00Z"}, {"starts_at": "2026-10-15T13:00:00"},
    {"title": " "}, {"message": "x"},
])
def test_invalid_alert_inputs_never_create_records(api, places, changes):
    district, *_ = places
    payload = {"title": "Flood warning", "message": "Flood water is rising.", "level": "RED", "place_id": district.id,
               "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(), **changes}
    assert api.client.post("/api/alerts", json=payload, headers=api.headers()).status_code == 422
    with api.sessions() as db:
        assert list(db.scalars(select(Alert))) == []


def test_update_validates_effective_window_and_missing_alerts(api, places):
    district, *_ = places
    alert = api.create(district.id)
    for payload in ({}, {"title": None}, {"place_id": "unknown"}, {"expires_at": "2020-01-01T00:00:00Z"}, {"created_by_id": 999}):
        assert api.client.patch(f"/api/alerts/{alert['id']}", json=payload, headers=api.headers()).status_code == 422
    after = api.client.get("/api/alerts", headers=api.headers()).json()[0]
    assert after["title"] == alert["title"] and after["place_id"] == district.id
    assert api.client.patch("/api/alerts/999999", json={"title": "Valid new title"}, headers=api.headers()).status_code == 404
    assert api.client.post("/api/alerts/999999/expire", headers=api.headers()).status_code == 404


def test_timezone_offsets_are_normalized_before_storage(api, places):
    district, *_ = places
    india = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(india)
    alert = api.create(district.id, starts_at=(now - timedelta(minutes=2)).isoformat(), expires_at=(now + timedelta(hours=1)).isoformat())
    assert alert["status"] == "ACTIVE"
    assert datetime.fromisoformat(alert["starts_at"].replace("Z", "+00:00")).hour == (now - timedelta(minutes=2)).astimezone(timezone.utc).hour


def test_existing_session_revocation_and_role_change_apply_to_alert_mutations(api, places):
    district, *_ = places
    alert = api.create(district.id)
    headers = api.headers()
    with api.sessions() as db:
        db.get(User, api.users["admin"]).role = Role.CITIZEN
        db.commit()
    assert api.client.patch(f"/api/alerts/{alert['id']}", json={"title": "Attempted update"}, headers=headers).status_code == 403
    with api.sessions() as db:
        token_session = db.scalar(select(TokenSession).where(TokenSession.user_id == api.users["admin"]))
        token_session.revoked_at = datetime.now(timezone.utc)
        db.commit()
    assert api.client.get("/api/alerts", headers=headers).status_code == 401


def resolved(place):
    return LocationExtraction(status="RESOLVED", place=place, candidates=[], matched_text=[place.name], reason="Canonical place supplied.")


def test_district_alert_matches_locality_and_other_district_does_not(api, places):
    district, locality, _, other = places
    alert = api.create(district.id)
    with api.sessions() as db:
        matched = match_alerts(db, resolved(locality))
        assert matched.status == "MATCH" and [item.id for item in matched.alerts] == [alert["id"]]
        assert match_alerts(db, resolved(other)).status == "NO_MATCH"
    response = api.client.post("/api/alerts/match", json={"message": "Flood water is rising", "reported_location": locality.name}, headers=api.headers("citizen"))
    assert response.status_code == 200 and response.json()["status"] == "MATCH", response.text


def test_locality_alert_does_not_cover_sibling_and_district_only_is_uncertain(api, places):
    district, locality, sibling, _ = places
    api.create(locality.id)
    with api.sessions() as db:
        assert match_alerts(db, resolved(locality)).status == "MATCH"
        assert match_alerts(db, resolved(sibling)).status == "NO_MATCH"
        uncertain = match_alerts(db, resolved(district))
        assert uncertain.status == "UNCERTAIN" and uncertain.alerts == []


def test_unresolved_geography_is_uncertain_even_with_empty_alert_database(api, places):
    _, locality, *_ = places
    with api.sessions() as db:
        assert match_alerts(db, resolved(locality)).status == "NO_MATCH"
        unknown = extract_location("Need help at an unknown place xyzzy.")
        assert match_alerts(db, unknown).status == "UNCERTAIN"


def test_matching_excludes_scheduled_naturally_expired_and_explicitly_expired_alerts(api, places):
    district, locality, *_ = places
    now = datetime.now(timezone.utc)
    api.create(district.id, starts_at=(now + timedelta(hours=1)).isoformat())
    api.create(district.id, starts_at=(now - timedelta(hours=3)).isoformat(), expires_at=(now - timedelta(hours=1)).isoformat())
    current = api.create(district.id)
    api.client.post(f"/api/alerts/{current['id']}/expire", headers=api.headers())
    with api.sessions() as db:
        assert match_alerts(db, resolved(locality)).status == "NO_MATCH"
