"""Live map coverage is scoped, time-bound and separate from geography precision."""
import os
from datetime import datetime, timedelta, timezone
import math

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["ALLOW_SQLITE_FOR_TESTS"] = "true"
os.environ["JWT_SECRET"] = "synthetic-overview-map-test-secret-2026"

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.ai.location_extractor import get_place, list_places
from backend.database.connection import Base, get_db
from backend.models import Role, Team, User
from backend.models.alert import Alert
from backend.models.shelter import Shelter
from backend.routers import overview_map
from backend.services.overview_map_service import district_boundaries, locality_coordinates, map_payload
from backend.utils.permissions import get_current_user


NOW = datetime(2026, 11, 5, 7, 0, tzinfo=timezone.utc)


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as session:
        session.add(User(id=1, full_name="Synthetic Map Admin", email="map@example.com", password_hash="unused", role=Role.ADMIN))
        session.commit()
        yield session
    engine.dispose()


def user(role=Role.CITIZEN, team_id=None):
    return User(id=1, full_name="Synthetic User", email="synthetic@example.com", role=role, team_id=team_id, active=True)


def add_alert(db, place_id="ernakulam-aluva", level="RED", **values):
    place = get_place(place_id)
    row = Alert(title="Synthetic flood alert", message="Exercise only: follow local guidance.",
                level=level, place_id=place.id, place_name=place.name, place_kind=place.kind,
                district_id=place.district_id, district=place.district, created_by_id=1,
                starts_at=values.pop("starts_at", NOW - timedelta(hours=1)),
                expires_at=values.pop("expires_at", NOW + timedelta(hours=1)), **values)
    db.add(row)
    db.commit()
    return row


def by_id(rows, identifier):
    return next(row for row in rows if row["id"] == identifier)


def test_all_districts_green_without_an_active_alert_and_no_guessed_points(db):
    result = map_payload(db, user(), now=NOW)
    assert len(result["districts"]) == 14
    assert {row["id"] for row in result["districts"]} == {p.id for p in list_places() if p.kind == "district"}
    assert all(row["level"] == row["district_level"] == "GREEN" and row["coverage"] == "none" for row in result["districts"])
    assert len(result["localities"]) == 100
    assert all(row["level"] == "GREEN" for row in result["localities"])
    assert sum(row["coordinate_status"] == "located" for row in result["localities"]) == 82
    unknown = by_id(result["localities"], "ernakulam-chellanam")
    assert unknown["latitude"] is unknown["longitude"] is unknown["coordinate_source"] is None
    assert "not proof of safety" in result["attribution"]["limitations"][0]


def test_locality_rollup_does_not_claim_district_wide_coverage(db):
    alert = add_alert(db)
    result = map_payload(db, user(), now=NOW)
    district = by_id(result["districts"], "ernakulam")
    assert district["level"] == "RED" and district["district_level"] == "GREEN"
    assert district["coverage"] == "locality" and district["locality_alert_count"] == 1
    aluva = by_id(result["localities"], "ernakulam-aluva")
    assert aluva["level"] == aluva["own_level"] == "RED"
    assert aluva["inherited_level"] == "GREEN"
    assert by_id(result["localities"], "ernakulam-kochi")["level"] == "GREEN"
    assert [row["id"] for row in aluva["alerts"]] == [alert.id]
    assert "created_by_id" not in aluva["alerts"][0]


def test_whole_district_alert_is_inherited_and_highest_active_level_wins(db):
    add_alert(db, "ernakulam", "ORANGE")
    add_alert(db, "ernakulam-aluva", "RED")
    add_alert(db, "ernakulam-kochi", "YELLOW")
    result = map_payload(db, user(), now=NOW)
    district = by_id(result["districts"], "ernakulam")
    assert district["level"] == "RED" and district["district_level"] == "ORANGE"
    assert district["coverage"] == "district" and district["active_alert_count"] == 3
    assert by_id(result["localities"], "ernakulam-aluva")["level"] == "RED"
    kochi = by_id(result["localities"], "ernakulam-kochi")
    assert kochi["level"] == "ORANGE" and kochi["own_level"] == "YELLOW"
    assert by_id(result["districts"], "kollam")["level"] == "GREEN"


def test_scheduled_expired_and_explicitly_expired_alerts_are_excluded(db):
    add_alert(db, "ernakulam", "RED", starts_at=NOW + timedelta(seconds=1))
    add_alert(db, "ernakulam", "RED", expires_at=NOW)
    add_alert(db, "ernakulam", "RED", expired_at=NOW - timedelta(minutes=1))
    add_alert(db, "ernakulam", "YELLOW", starts_at=NOW)
    result = map_payload(db, user(), now=NOW)
    district = by_id(result["districts"], "ernakulam")
    assert district["level"] == "YELLOW" and district["active_alert_count"] == 1


def test_missing_locality_coordinates_do_not_drop_the_alert(db):
    alert = add_alert(db, "ernakulam-chellanam", "ORANGE")
    result = map_payload(db, user(), now=NOW)
    assert result["unlocated_alert_count"] == 1
    point = by_id(result["localities"], "ernakulam-chellanam")
    assert point["coordinate_status"] == "unlocated" and point["level"] == "ORANGE"
    assert point["alerts"][0]["id"] == alert.id
    assert by_id(result["districts"], "ernakulam")["level"] == "ORANGE"


def test_shelter_freshness_coordinates_capacity_and_staff_permissions(db):
    team = Team(name="Synthetic Shelter Team", team_type="Shelter")
    db.add(team)
    db.flush()
    db.add_all([
        Shelter(name="Recent record", district="Ernakulam", capacity=10, occupied=3, status="OPEN", contact="12345",
                latitude=10.1, longitude=76.35, team_id=team.id, updated_at=NOW - timedelta(minutes=1)),
        Shelter(name="Stale closed", capacity=10, occupied=0, status="CLOSED", updated_at=NOW - timedelta(hours=1)),
        Shelter(name="Full record", capacity=5, occupied=5, status="FULL", latitude=10.2, longitude=76.4, updated_at=NOW),
        Shelter(name="Invalid coordinates", capacity=5, occupied=0, status="OPEN", latitude=999, longitude=76, updated_at=NOW),
    ])
    db.commit()
    result = map_payload(db, user(), now=NOW)
    rows = {row["name"]: row for row in result["shelters"]}
    assert rows["Recent record"]["available_capacity"] == 7 and rows["Recent record"]["can_register"]
    assert rows["Recent record"]["freshness_status"] == "recent"
    assert rows["Stale closed"]["freshness_status"] == "stale" and not rows["Stale closed"]["can_register"]
    assert not rows["Full record"]["can_register"]
    assert result["unlocated_shelter_count"] == 2
    assert rows["Invalid coordinates"]["latitude"] is None
    assert not any(row["can_manage_registrations"] for row in rows.values())
    admin_rows = map_payload(db, user(Role.ADMIN), now=NOW)["shelters"]
    assert all(row["can_manage_registrations"] and not row["can_register"] for row in admin_rows)
    staff_rows = map_payload(db, user(Role.RESPONSE_TEAM, team.id), now=NOW)["shelters"]
    assert [row["name"] for row in staff_rows if row["can_manage_registrations"]] == ["Recent record"]


def test_geography_is_local_complete_and_matches_catalog_ids():
    boundaries = district_boundaries()
    assert boundaries["type"] == "FeatureCollection" and len(boundaries["features"]) == 14
    assert {f["properties"]["id"] for f in boundaries["features"]} == {p.id for p in list_places() if p.kind == "district"}
    assert all(f["geometry"]["type"] in {"Polygon", "MultiPolygon"} for f in boundaries["features"])
    points = locality_coordinates()
    assert len(points) == 82
    for identifier, point in points.items():
        place = get_place(identifier)
        assert place and place.kind == "locality" and point["district_id"] == place.district_id
        assert math.isfinite(point["latitude"]) and math.isfinite(point["longitude"])
        assert 8 <= point["latitude"] <= 13 and 74.5 <= point["longitude"] <= 77.5
        assert point["source_url"].startswith("https://www.geonames.org/")


@pytest.mark.parametrize("written,expected", [
    (" TrIvAnDrUm ", "thiruvananthapuram"),
    ("CALICUT", "kozhikode"),
    ("Kasargod", "kasaragod"),
    ("തിരുവനന്തപുരം", "thiruvananthapuram"),
    ("Ernakulam", "ernakulam"),
    ("Cochin", None),  # A known locality alias is not a district alias.
    ("Kochi", None),
    ("Ernakulam district near Aluva", None),
    ("Unknown district", None),
    ("", None),
    (None, None),
])
def test_shelter_district_aliases_resolve_exactly_without_guessing_or_rewriting(db, written, expected):
    shelter = Shelter(name="Synthetic alias shelter", district=written, locality="Aluva",
                      latitude=10.1, longitude=76.35, capacity=2, occupied=0, status="OPEN", updated_at=NOW)
    db.add(shelter)
    db.commit()
    row = map_payload(db, user(), now=NOW)["shelters"][0]
    assert row["district_id"] == expected
    assert row["district"] == written and shelter.district == written


def test_map_endpoints_require_login_and_are_available_to_all_three_roles(db):
    app = FastAPI()
    app.include_router(overview_map.router)
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        for path in ("/api/overview/map", "/api/overview/district-boundaries"):
            assert client.get(path).status_code == 401
        for role in Role:
            app.dependency_overrides[get_current_user] = lambda role=role: user(role)
            response = client.get("/api/overview/map")
            assert response.status_code == 200 and len(response.json()["districts"]) == 14
            assert client.get("/api/overview/district-boundaries").status_code == 200
