"""Isolated checks for tab bearer sessions, account details and role access."""
import json
import os

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["ALLOW_SQLITE_FOR_TESTS"] = "true"
os.environ["JWT_SECRET"] = "session-ui-tests-only-synthetic-secret-2026"

from dataclasses import dataclass, field
from html import escape
from html.parser import HTMLParser
from importlib import import_module

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database.connection import Base, get_db
from backend.main import app as api
from backend.models import Role, Team, User
from backend.utils.security import hash_password

web_ui = import_module("web.app")
PASSWORD = "Synthetic-session-ui-pass!2026"
WORKSPACES = (
    (Role.CITIZEN, "Citizen workspace", "/api/workspaces/citizen"),
    (Role.ADMIN, "Admin workspace", "/api/workspaces/admin"),
    (Role.RESPONSE_TEAM, "Response team workspace", "/api/workspaces/response-team"),
)


@dataclass
class SessionUI:
    client: TestClient
    users: dict
    tokens: dict = field(default_factory=dict, repr=False)

    def token(self, role):
        if role not in self.tokens:
            response = self.client.post("/api/auth/login", json={
                "email": self.users[role]["email"], "password": PASSWORD,
            })
            assert response.status_code == 200
            self.tokens[role] = response.json()["access_token"]
        return self.tokens[role]

    def headers(self, role, **extra):
        return {"X-ResQ-Page": "true", "Authorization": f"Bearer {self.token(role)}", **extra}

    def post(self, path, role=None, **data):
        if not self.client.cookies.get(web_ui.CSRF_COOKIE):
            self.client.get("/login")
        headers = {"HX-Request": "true"}
        if role is not None:
            headers.update(self.headers(role))
        return self.client.post(path, headers=headers, data={
            "_csrf": self.client.cookies.get(web_ui.CSRF_COOKIE), **data,
        })


@pytest.fixture(scope="module")
def session_ui_password_hash():
    return hash_password(PASSWORD)


@pytest.fixture
def session_ui(session_ui_password_hash):
    test_engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )

    @event.listens_for(test_engine, "connect")
    def foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(test_engine)
    sessions = sessionmaker(bind=test_engine, expire_on_commit=False)
    users = {}
    with sessions() as db:
        team = Team(name="Session UI synthetic team", team_type="Rescue")
        db.add(team)
        db.flush()
        for role in Role:
            user = User(
                full_name=f"<script>session-ui-{role.value}</script> & profile",
                email=f"{role.value}&profile@example.com",
                password_hash=session_ui_password_hash, role=role,
                team_id=team.id if role == Role.RESPONSE_TEAM else None,
            )
            db.add(user)
            db.flush()
            users[role] = {"id": user.id, "full_name": user.full_name,
                           "email": user.email, "team_id": user.team_id}
        db.commit()

    def override_database():
        with sessions() as db:
            yield db

    previous_overrides = api.dependency_overrides.copy()
    api.dependency_overrides[get_db] = override_database
    try:
        with TestClient(web_ui.app, follow_redirects=False) as client:
            yield SessionUI(client, users)
    finally:
        api.dependency_overrides.clear()
        api.dependency_overrides.update(previous_overrides)
        test_engine.dispose()


class AccountFacts(HTMLParser):
    def __init__(self, markup):
        super().__init__()
        self.facts = {}
        self.label = None
        self.active = None
        self.parts = []
        self.feed(markup)

    def handle_starttag(self, tag, _attrs):
        if tag in {"dt", "dd"}:
            self.active, self.parts = tag, []

    def handle_data(self, data):
        if self.active:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == self.active:
            text = " ".join("".join(self.parts).split())
            if tag == "dt":
                self.label = text
            else:
                self.facts[self.label] = text
            self.active = None


class PermissionRows(HTMLParser):
    def __init__(self, markup):
        super().__init__()
        self.rows = []
        self.row = None
        self.cell = None
        self.feed(markup)

    def handle_starttag(self, tag, _attrs):
        if tag == "tr":
            self.row = []
        elif tag in {"th", "td"} and self.row is not None:
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in {"th", "td"} and self.cell is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None


@pytest.mark.parametrize("path", ["/dashboard", "/account", "/permissions", "/reports"])
def test_document_navigation_only_exposes_public_bootstrap(session_ui, path):
    response = session_ui.client.get(path, headers={
        "Authorization": f"Bearer {session_ui.token(Role.ADMIN)}",
    })
    assert response.status_code == 200
    assert "data-session-bootstrap" in response.text
    assert 'id="app-root" data-authenticated="false"' in response.text
    assert "<html" in response.text.lower()
    assert "Signed-in profile" not in response.text
    for user in session_ui.users.values():
        assert escape(user["full_name"]) not in response.text
        assert escape(user["email"]) not in response.text


@pytest.mark.parametrize("role", list(Role))
def test_explicit_tab_bearer_renders_escaped_account_fields(session_ui, role):
    response = session_ui.client.get("/account", headers=session_ui.headers(role))
    assert response.status_code == 200
    assert "data-session-bootstrap" not in response.text
    assert 'id="app-root" data-authenticated="true"' in response.text
    user = session_ui.users[role]
    assert user["full_name"] not in response.text
    assert escape(user["full_name"]) in response.text
    assert escape(user["email"]) in response.text
    facts = AccountFacts(response.text).facts
    assert facts["Full name"] == user["full_name"]
    assert facts["Email address"] == user["email"]
    assert facts["Role"] == role.value.replace("_", " ").title()
    assert facts["User ID"] == str(user["id"])
    if user["team_id"] is None:
        assert "Team ID" not in facts
    else:
        assert facts["Team ID"] == str(user["team_id"])


def test_legacy_cookie_cannot_authenticate_or_override_explicit_tab(session_ui):
    session_ui.client.cookies.set(web_ui.LEGACY_TOKEN_COOKIE, session_ui.token(Role.ADMIN))
    anonymous = session_ui.client.get("/account", headers={
        "X-ResQ-Page": "true", "HX-Request": "true",
    })
    assert anonymous.headers.get("HX-Redirect") == "/login"
    assert "Signed-in profile" not in anonymous.text
    assert "Max-Age=0" in anonymous.headers.get("set-cookie", "")

    session_ui.client.cookies.set(web_ui.LEGACY_TOKEN_COOKIE, session_ui.token(Role.ADMIN))
    citizen = session_ui.client.get("/account", headers=session_ui.headers(Role.CITIZEN))
    assert citizen.status_code == 200
    assert AccountFacts(citizen.text).facts["Role"] == "Citizen"


@pytest.mark.parametrize("mode", ["login", "register"])
def test_ui_auth_delivers_token_by_204_trigger_without_auth_cookie(session_ui, mode):
    credentials = {"email": session_ui.users[Role.CITIZEN]["email"], "password": PASSWORD}
    if mode == "register":
        credentials.update(full_name="New session UI citizen", email="new.session.ui@example.com")
    response = session_ui.post(f"/ui/{mode}", **credentials)
    assert response.status_code == 204
    assert response.content == b""
    assert "HX-Redirect" not in response.headers
    trigger = json.loads(response.headers["HX-Trigger"])
    assert set(trigger) == {"resq:authenticated"}
    token = trigger["resq:authenticated"]["access_token"]
    assert isinstance(token, str) and token
    assert web_ui.LEGACY_TOKEN_COOKIE not in session_ui.client.cookies
    assert web_ui.LEGACY_TOKEN_COOKIE not in response.headers.get("set-cookie", "")
    profile = session_ui.client.get("/api/users/me", headers={"Authorization": f"Bearer {token}"})
    assert profile.status_code == 200
    assert profile.json()["role"] == "citizen"


def test_invalid_session_redirects_with_expiry_signal_and_notice(session_ui):
    response = session_ui.client.get("/account", headers={
        "X-ResQ-Page": "true", "HX-Request": "true",
        "Authorization": "Bearer malformed-synthetic-token",
    })
    assert response.headers.get("HX-Redirect") == "/login?notice=expired"
    assert response.headers.get("X-ResQ-Session") == "expired"
    notice = session_ui.client.get("/login?notice=expired", headers={"X-ResQ-Page": "true"})
    assert notice.status_code == 200
    assert "Your session has expired. Please sign in again." in notice.text


def test_profile_outage_serves_reconnect_without_expiring_session(session_ui, monkeypatch):
    headers = session_ui.headers(Role.CITIZEN)
    original_api_call = web_ui.api_call

    async def unavailable_profile(request, method, path, payload=None):
        if path == "/api/users/me":
            return httpx.Response(503, json={"detail": "Synthetic unavailable service"})
        return await original_api_call(request, method, path, payload)

    with monkeypatch.context() as patch:
        patch.setattr(web_ui, "api_call", unavailable_profile)
        response = session_ui.client.get("/account?return=details", headers=headers)
    assert response.status_code == 503
    assert "Reconnect your workspace." in response.text
    assert 'href="/account?return=details"' in response.text
    assert "X-ResQ-Session" not in response.headers
    assert "HX-Redirect" not in response.headers
    assert 'action="/ui/login"' not in response.text
    assert session_ui.client.get("/api/users/me", headers=headers).status_code == 200


@pytest.mark.parametrize("post_path,retry_path,role", [
    ("/ui/reports", "/reports/new", Role.CITIZEN),
    ("/ui/reports/1/review", "/reports/1", Role.ADMIN),
    ("/ui/reports/1/assign", "/reports/1", Role.ADMIN),
])
def test_profile_outage_during_post_retries_a_real_get_page(
    session_ui, monkeypatch, post_path, retry_path, role,
):
    if retry_path == "/reports/1":
        report = session_ui.client.post("/api/incidents/", headers=session_ui.headers(Role.CITIZEN), json={
            "message": "Synthetic incident for reconnect navigation.", "location": "Kochi",
        })
        assert report.status_code == 201
        assert report.json()["id"] == 1
    headers = session_ui.headers(role)
    original_api_call = web_ui.api_call

    async def unavailable_profile(request, method, path, payload=None):
        if path == "/api/users/me":
            return httpx.Response(503, json={"detail": "Synthetic unavailable service"})
        return await original_api_call(request, method, path, payload)

    with monkeypatch.context() as patch:
        patch.setattr(web_ui, "api_call", unavailable_profile)
        response = session_ui.post(post_path, role)
    assert response.status_code == 503
    assert "Reconnect your workspace." in response.text
    assert f'href="{retry_path}"' in response.text
    assert f'href="{post_path}"' not in response.text
    assert "X-ResQ-Session" not in response.headers
    assert "HX-Redirect" not in response.headers
    assert 'action="/ui/login"' not in response.text
    assert session_ui.client.get(retry_path, headers=headers).status_code == 200
    assert session_ui.client.get("/api/users/me", headers=headers).status_code == 200


def test_logout_outage_announces_unconfirmed_local_sign_out(session_ui, monkeypatch):
    headers = session_ui.headers(Role.CITIZEN)
    original_api_call = web_ui.api_call

    async def unavailable_logout(request, method, path, payload=None):
        if path == "/api/auth/logout":
            return httpx.Response(503, json={"detail": "Synthetic unavailable service"})
        return await original_api_call(request, method, path, payload)

    with monkeypatch.context() as patch:
        patch.setattr(web_ui, "api_call", unavailable_logout)
        response = session_ui.post("/ui/logout", Role.CITIZEN)
    assert response.status_code == 204
    assert response.content == b""
    trigger = json.loads(response.headers["HX-Trigger"])
    assert trigger == {"resq:signed-out": {"notice": "logout-unconfirmed"}}
    assert session_ui.client.get("/api/users/me", headers=headers).status_code == 200
    notice = session_ui.client.get("/login?notice=logout-unconfirmed", headers={"X-ResQ-Page": "true"})
    assert "The server could not confirm session revocation." in notice.text
    assert "may remain valid until it expires" in notice.text


def test_rejected_logout_does_not_claim_confirmed_revocation(session_ui):
    session_ui.client.get("/login")
    response = session_ui.client.post("/ui/logout", headers={
        "HX-Request": "true", "Authorization": "Bearer malformed-synthetic-token",
    }, data={"_csrf": session_ui.client.cookies.get(web_ui.CSRF_COOKIE)})
    assert response.status_code == 204
    assert response.content == b""
    assert json.loads(response.headers["HX-Trigger"]) == {
        "resq:signed-out": {"notice": "logout-unconfirmed"},
    }


def test_confirmed_logout_revokes_only_supplied_session(session_ui):
    citizen_headers = session_ui.headers(Role.CITIZEN)
    admin_headers = session_ui.headers(Role.ADMIN)
    response = session_ui.post("/ui/logout", Role.CITIZEN)
    assert response.status_code == 204
    assert json.loads(response.headers["HX-Trigger"]) == {
        "resq:signed-out": {"notice": "signed-out"},
    }
    assert session_ui.client.get("/api/users/me", headers=citizen_headers).status_code == 401
    assert session_ui.client.get("/api/users/me", headers=admin_headers).status_code == 200


@pytest.mark.parametrize("role", list(Role))
def test_permissions_page_matches_actual_server_role_matrix(session_ui, role):
    headers = session_ui.headers(role)
    response = session_ui.client.get("/permissions", headers=headers)
    assert response.status_code == 200
    rows = PermissionRows(response.text).rows
    for workspace_role, title, path in WORKSPACES:
        direct = session_ui.client.get(path, headers=headers)
        expected = 200 if role == workspace_role else 403
        assert direct.status_code == expected
        row = next(row for row in rows if row[0].startswith(title))
        assert f"HTTP {direct.status_code}" in row[2]
        assert ("Allowed" if expected == 200 else "Denied by server") in row[1]
    assert "Check failed" not in response.text
    # A role-denied workspace must not clear the valid tab session.
    assert session_ui.client.get("/api/users/me", headers=headers).status_code == 200
