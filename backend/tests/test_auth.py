"""Athul's Week 1 authentication and role-permission API checks.

Every test has a fresh in-memory database. These checks never read or change the
full project's accounts, incident reports, team assignments, or demo database.
"""

import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["ALLOW_SQLITE_FOR_TESTS"] = "true"
os.environ["JWT_SECRET"] = "athul-isolated-auth-tests-only-secret-2026"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database.connection import Base, get_db
from backend.main import app
from backend.models import Role, TokenSession, User
from backend.utils.security import hash_password, verify_password


TEST_PASSWORD = "Synthetic-auth-pass!2026"
WORKSPACES = {
    "citizen": "/api/workspaces/citizen",
    "admin": "/api/workspaces/admin",
    "response_team": "/api/workspaces/response-team",
}


@dataclass
class Harness:
    client: TestClient
    sessions: object
    users: dict[str, int]
    token_cache: dict[str, str] = field(default_factory=dict)

    def login(self, role: str) -> dict:
        response = self.client.post("/api/auth/login", json={
            "email": f"{role}@example.com", "password": TEST_PASSWORD,
        })
        assert response.status_code == 200, response.text
        return response.json()

    def headers(self, role: str) -> dict[str, str]:
        if role not in self.token_cache:
            self.token_cache[role] = self.login(role)["access_token"]
        return {"Authorization": f"Bearer {self.token_cache[role]}"}


@pytest.fixture(scope="session")
def synthetic_password_hash():
    return hash_password(TEST_PASSWORD)


@pytest.fixture
def api(synthetic_password_hash):
    test_engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )

    @event.listens_for(test_engine, "connect")
    def foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(test_engine)
    sessions = sessionmaker(bind=test_engine, expire_on_commit=False)
    with sessions() as db:
        accounts = [
            User(full_name="Test Citizen", email="citizen@example.com",
                 role=Role.CITIZEN, password_hash=synthetic_password_hash),
            User(full_name="Test Admin", email="admin@example.com",
                 role=Role.ADMIN, password_hash=synthetic_password_hash),
            User(full_name="Test Team Member", email="response_team@example.com",
                 role=Role.RESPONSE_TEAM, password_hash=synthetic_password_hash),
        ]
        db.add_all(accounts)
        db.commit()
        user_ids = {user.role.value: user.id for user in accounts}

    def override_database():
        with sessions() as db:
            yield db

    previous_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = override_database
    try:
        with TestClient(app) as client:
            yield Harness(client, sessions, user_ids)
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)
        test_engine.dispose()


def test_registration_creates_citizen_and_hashes_password(api):
    response = api.client.post("/api/auth/register", json={
        "full_name": "  New Citizen  ", "email": " NEW@EXAMPLE.COM ",
        "password": TEST_PASSWORD,
    })
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["user"]["role"] == "citizen"
    assert body["user"]["full_name"] == "New Citizen"
    assert body["user"]["email"] == "new@example.com"
    assert "password" not in body["user"] and "password_hash" not in body["user"]
    with api.sessions() as db:
        user = db.scalar(select(User).where(User.email == "new@example.com"))
        assert user.password_hash != TEST_PASSWORD
        assert verify_password(TEST_PASSWORD, user.password_hash)
    headers = {"Authorization": f"Bearer {body['access_token']}"}
    assert api.client.get("/api/users/me", headers=headers).json()["id"] == body["user"]["id"]


def test_duplicate_email_is_case_insensitive(api):
    response = api.client.post("/api/auth/register", json={
        "full_name": "Duplicate Citizen", "email": " CITIZEN@EXAMPLE.COM ",
        "password": TEST_PASSWORD,
    })
    assert response.status_code == 409
    with api.sessions() as db:
        assert len(list(db.scalars(select(User).where(User.email == "citizen@example.com")))) == 1


@pytest.mark.parametrize("privilege", [{"role": "admin"}, {"role": "response_team"}, {"team_id": 1}])
def test_public_registration_rejects_privilege_fields(api, privilege):
    response = api.client.post("/api/auth/register", json={
        "full_name": "Escalation Attempt", "email": "attempt@example.com",
        "password": TEST_PASSWORD, **privilege,
    })
    assert response.status_code == 422
    with api.sessions() as db:
        assert db.scalar(select(User).where(User.email == "attempt@example.com")) is None


@pytest.mark.parametrize("change", [
    {"full_name": " " * 10}, {"email": "invalid-email"},
    {"password": "short"}, {"password": 1234567890},
])
def test_invalid_registration_creates_no_account(api, change):
    response = api.client.post("/api/auth/register", json={
        "full_name": "Invalid Citizen", "email": "invalid@example.com",
        "password": TEST_PASSWORD, **change,
    })
    assert response.status_code == 422
    with api.sessions() as db:
        assert len(list(db.scalars(select(User)))) == 3


def test_password_whitespace_remains_significant(api):
    password = f"  {TEST_PASSWORD}  "
    response = api.client.post("/api/auth/register", json={
        "full_name": "Whitespace Citizen", "email": "spaces@example.com", "password": password,
    })
    assert response.status_code == 201
    assert api.client.post("/api/auth/login", json={
        "email": "spaces@example.com", "password": TEST_PASSWORD,
    }).status_code == 401
    assert api.client.post("/api/auth/login", json={
        "email": "spaces@example.com", "password": password,
    }).status_code == 200


def test_correct_login_normalizes_email(api):
    response = api.client.post("/api/auth/login", json={
        "email": " CITIZEN@EXAMPLE.COM ", "password": TEST_PASSWORD,
    })
    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"
    assert response.json()["user"]["role"] == "citizen"


@pytest.mark.parametrize("email,password", [
    ("citizen@example.com", "Incorrect-password!2026"),
    ("missing@example.com", TEST_PASSWORD),
])
def test_invalid_login_rejected_without_creating_session(api, email, password):
    response = api.client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    with api.sessions() as db:
        assert list(db.scalars(select(TokenSession))) == []


def test_logout_revokes_only_the_current_session(api):
    first = {"Authorization": f"Bearer {api.login('citizen')['access_token']}"}
    second = {"Authorization": f"Bearer {api.login('citizen')['access_token']}"}
    assert api.client.post("/api/auth/logout", headers=first).status_code == 204
    assert api.client.get("/api/users/me", headers=first).status_code == 401
    assert api.client.post("/api/auth/logout", headers=first).status_code == 401
    assert api.client.get("/api/users/me", headers=second).status_code == 200
    with api.sessions() as db:
        sessions = list(db.scalars(select(TokenSession).where(TokenSession.user_id == api.users["citizen"])))
        assert len(sessions) == 2
        assert sum(session.revoked_at is not None for session in sessions) == 1


def test_expired_persisted_session_rejects_token(api):
    headers = api.headers("citizen")
    with api.sessions() as db:
        session = db.scalar(select(TokenSession).where(TokenSession.user_id == api.users["citizen"]))
        session.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
    assert api.client.get("/api/users/me", headers=headers).status_code == 401


def test_deleted_persisted_session_rejects_token(api):
    headers = api.headers("citizen")
    with api.sessions() as db:
        session = db.scalar(select(TokenSession).where(TokenSession.user_id == api.users["citizen"]))
        db.delete(session)
        db.commit()
    assert api.client.get("/api/users/me", headers=headers).status_code == 401


def test_inactive_account_rejects_existing_token_and_new_login(api):
    headers = api.headers("citizen")
    with api.sessions() as db:
        db.get(User, api.users["citizen"]).active = False
        db.commit()
    assert api.client.get("/api/users/me", headers=headers).status_code == 401
    assert api.client.post("/api/auth/login", json={
        "email": "citizen@example.com", "password": TEST_PASSWORD,
    }).status_code == 401


@pytest.mark.parametrize("path", ["/api/users/me", *WORKSPACES.values()])
def test_protected_routes_reject_missing_and_invalid_authentication(api, path):
    assert api.client.get(path).status_code == 401
    assert api.client.get(path, headers={"Authorization": "Bearer invalid-token"}).status_code == 401


def test_logout_requires_authentication(api):
    assert api.client.post("/api/auth/logout").status_code == 401


@pytest.mark.parametrize("role", list(WORKSPACES))
def test_roles_can_enter_only_their_own_workspace(api, role):
    headers = api.headers(role)
    account = api.client.get("/api/users/me", headers=headers)
    assert account.status_code == 200
    assert account.json()["role"] == role
    assert "password_hash" not in account.json()
    for workspace_role, path in WORKSPACES.items():
        response = api.client.get(path, headers=headers)
        assert response.status_code == (200 if workspace_role == role else 403)
        if workspace_role == role:
            assert response.json()["role"] == role
            assert response.json()["title"]
            assert response.json()["message"]


def test_role_changes_take_effect_for_an_existing_session(api):
    headers = api.headers("citizen")
    assert api.client.get(WORKSPACES["citizen"], headers=headers).status_code == 200
    with api.sessions() as db:
        db.get(User, api.users["citizen"]).role = Role.ADMIN
        db.commit()
    assert api.client.get(WORKSPACES["citizen"], headers=headers).status_code == 403
    assert api.client.get(WORKSPACES["admin"], headers=headers).status_code == 200


def test_health_checks_database_connection(api):
    response = api.client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["database"] == "connected"
