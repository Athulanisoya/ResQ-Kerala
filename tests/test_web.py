"""Presentation-layer checks: HTML, cookies, CSRF and UI -> JSON API workflow."""
import os

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["ALLOW_SQLITE_FOR_TESTS"] = "true"
os.environ["JWT_SECRET"] = "web-tests-only-synthetic-secret-with-32-characters"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database.connection import Base, get_db
from backend.main import app as api
from backend.models import Role, User
from backend.models.team import Team
from backend.utils.security import hash_password
from web.app import app, CSRF_COOKIE, TOKEN_COOKIE

PASSWORD = "Synthetic-ui-test!2026"


@pytest.fixture
def clients():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as db:
        team = Team(name="Alappuzha Response Team", team_type="rescue")
        db.add(team)
        db.flush()
        for role in Role:
            db.add(User(full_name=f"Test {role.value}", email=f"{role.value}@example.com", password_hash=hash_password(PASSWORD),
                        role=role, team_id=team.id if role == Role.RESPONSE_TEAM else None))
        db.commit()

    def override():
        with sessions() as db:
            yield db

    api.dependency_overrides[get_db] = override
    with TestClient(app) as citizen, TestClient(app) as admin, TestClient(app) as team_client:
        yield citizen, admin, team_client
    api.dependency_overrides.clear()
    engine.dispose()


def post(client, path, **data):
    return client.post(path, data={"_csrf": client.cookies.get(CSRF_COOKIE), **data}, headers={"HX-Request": "true"})


def login(client, role):
    assert client.get("/login").status_code == 200
    response = post(client, "/ui/login", email=f"{role}@example.com", password=PASSWORD)
    assert response.status_code == 200
    assert response.headers["HX-Redirect"] == "/dashboard"
    assert "HttpOnly" in response.headers["set-cookie"]


def test_csrf_and_registration(clients):
    client, _, _ = clients
    assert client.get("/register").status_code == 200
    assert client.post("/ui/register", data={"email": "new@example.com"}).status_code == 403
    assert client.post("/ui/register", data={"_csrf": "invalid-☃"}).status_code == 403
    cross_site = client.post("/ui/register", data={"_csrf": client.cookies.get(CSRF_COOKIE)}, headers={"Origin": "https://other.example"})
    assert cross_site.status_code == 403
    registered = post(client, "/ui/register", email="new@example.com", full_name="New Citizen", password=PASSWORD)
    assert registered.status_code == 200
    assert registered.headers["HX-Redirect"] == "/dashboard"
    assert client.get("/dashboard").status_code == 200


def test_htmx_fragments_validation_and_logout(clients):
    citizen, _, _ = clients
    citizen.get("/login")
    invalid_login = post(citizen, "/ui/login", email="citizen@example.com", password="incorrect-password")
    assert invalid_login.status_code == 401
    assert "alert" in invalid_login.text
    login(citizen, "citizen")
    full = citizen.get("/reports/new")
    partial = citizen.get("/reports/new", headers={"HX-Request": "true"})
    assert "<html" in full.text.lower()
    assert "<html" not in partial.text.lower()
    assert "hx-post" in partial.text
    invalid = post(citizen, "/ui/reports", message="<script>alert(1)</script>", location="K", people_affected="-1")
    assert invalid.status_code == 422
    assert "<script>alert(1)</script>" not in invalid.text
    assert "&lt;script&gt;" in invalid.text
    token = citizen.cookies.get(TOKEN_COOKIE)
    assert post(citizen, "/ui/logout").headers["HX-Redirect"] == "/login"
    assert not citizen.cookies.get(TOKEN_COOKIE)
    assert citizen.get("/api/users/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_complete_week1_through_html_forms(clients):
    citizen, admin, team = clients
    login(citizen, "citizen")
    created = post(citizen, "/ui/reports", message="Flood water entered our home near the bridge.", location="Chengannur", people_affected="4", help_required="Evacuation")
    assert created.status_code == 200
    path = created.headers["HX-Redirect"]
    incident_id = int(path.rsplit("/", 1)[-1])
    assert "Submitted" in citizen.get(path).text
    login(admin, "admin")
    assert "Chengannur" in admin.get("/reports").text
    for status in ("UNDER_REVIEW", "VERIFIED"):
        response = post(admin, f"/ui/reports/{incident_id}/review", status=status, note="Reviewed incident details")
        assert response.status_code == 200
        assert response.headers["HX-Redirect"] == path
    assigned = post(admin, f"/ui/reports/{incident_id}/assign", team_id="1")
    assert assigned.status_code == 200
    assert assigned.headers["HX-Redirect"] == path
    history_page = citizen.get(path)
    assert "Assigned" in history_page.text
    assert "Reviewed incident details" in history_page.text
    login(team, "response_team")
    assert "Chengannur" in team.get("/reports").text
    assert "Chengannur" in team.get(path).text
    assert post(team, f"/ui/reports/{incident_id}/review", status="VERIFIED").status_code == 403
