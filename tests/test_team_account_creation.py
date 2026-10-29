"""Administrator-created team logins preserve role and membership boundaries."""
import pytest
from sqlalchemy import select
from backend.tests.test_auth import api, synthetic_password_hash
from backend.models import Role, Team, User
from backend.models.admin_audit import AdminChange
from backend.utils.security import verify_password
from tests.test_operations_ui import operations_clients, submit

PASSWORD = "Synthetic-team-account!2026"
PATH = "/api/management/team-accounts"


def active_team(api, status="AVAILABLE"):
    with api.sessions() as db:
        team = Team(name="Synthetic shelter members", team_type="Shelter", status=status)
        db.add(team); db.commit()
        return team.id


def payload(team_id, **extra):
    return {"full_name": "  New Team Member  ", "email": " NEW.TEAM@EXAMPLE.COM ",
            "password": PASSWORD, "team_id": team_id, **extra}


def test_admin_can_create_team_account_and_member_can_sign_in(api):
    team_id = active_team(api)
    admin = api.headers("admin")
    result = api.client.post(PATH, headers=admin, json=payload(team_id))
    assert result.status_code == 201, result.text
    body = result.json()
    assert body["role"] == "response_team" and body["team_id"] == team_id
    assert body["full_name"] == "New Team Member" and body["email"] == "new.team@example.com"
    assert PASSWORD not in result.text and "password" not in body and "password_hash" not in body
    with api.sessions() as db:
        row = db.get(User, body["id"])
        assert row.password_hash != PASSWORD and verify_password(PASSWORD, row.password_hash)
        audit = db.scalar(select(AdminChange).where(AdminChange.target_id == row.id, AdminChange.action == "create"))
        assert audit is not None and PASSWORD not in audit.details and "password_hash" not in audit.details
    signed_in = api.client.post("/api/auth/login", json={"email": body["email"], "password": PASSWORD})
    assert signed_in.status_code == 200
    assert signed_in.json()["user"]["role"] == "response_team"
    assert signed_in.json()["user"]["team_id"] == team_id
    assert api.client.get("/api/users/me", headers=admin).json()["role"] == "admin"
    duplicate = api.client.post(PATH, headers=admin, json=payload(team_id, email="NEW.TEAM@example.com"))
    assert duplicate.status_code == 409


@pytest.mark.parametrize("role,status", [(None, 401), ("citizen", 403), ("response_team", 403)])
def test_team_account_provisioning_is_admin_only(api, role, status):
    response = api.client.post(PATH, headers=api.headers(role) if role else {}, json=payload(active_team(api)))
    assert response.status_code == status


def test_team_accounts_require_valid_active_team_and_fixed_role(api):
    admin = api.headers("admin")
    team_id = active_team(api, status="OFFLINE")
    assert api.client.post(PATH, headers=admin, json=payload(team_id)).status_code == 409
    assert api.client.post(PATH, headers=admin, json=payload(99999)).status_code == 404
    for changes in ({"team_id": None}, {"password": "short"}, {"role": "admin"}, {"full_name": "  "}, {"email": "invalid"}):
        assert api.client.post(PATH, headers=admin, json={**payload(team_id), **changes}).status_code == 422
    assert api.client.post("/api/auth/register", json={**payload(team_id), "role": "response_team"}).status_code == 422


def test_password_validation_never_echoes_supplied_secrets(api):
    secret = "Synthetic-private-password-" * 8
    body = payload(active_team(api), password=secret)
    response = api.client.post(PATH, headers=api.headers("admin"), json=body)
    assert response.status_code == 422
    assert secret not in response.text
    assert response.json()["detail"][0]["loc"] == ["body", "password"]
    assert "input" not in response.json()["detail"][0]
    for path in ("/api/auth/register", "/api/auth/login"):
        public_body = {"email": "private@example.com", "password": secret}
        if path.endswith("register"):
            public_body["full_name"] = "Synthetic Private Account"
        invalid = api.client.post(path, json=public_body)
        assert invalid.status_code == 422 and secret not in invalid.text


def test_admin_team_account_form_creates_login_without_echoing_password(operations_clients):
    admin, citizen = operations_clients["admin"], operations_clients["citizen"]
    page = admin.get("/management", headers={"HX-Request": "true"})
    assert '<section id="create-team-account"' in page.text
    assert 'action="/ui/management/team-accounts"' in page.text
    assert 'Team member name' in page.text and 'Assigned team' in page.text
    body = {"full_name": "New Field Member", "email": "field-member@example.com", "team_id": "1", "password": PASSWORD, "confirm_password": PASSWORD}
    assert submit(citizen, "/ui/management/team-accounts", **body).status_code == 403
    mismatch = submit(admin, "/ui/management/team-accounts", **{**body, "confirm_password": "Different-test-password"})
    assert mismatch.status_code == 422 and "passwords do not match" in mismatch.text
    assert PASSWORD not in mismatch.text and 'value="New Field Member"' in mismatch.text
    created = submit(admin, "/ui/management/team-accounts", **body)
    assert created.status_code == 200 and "Team account created" in created.text
    assert PASSWORD not in created.text
    signed_in = citizen.post("/api/auth/login", json={"email": "field-member@example.com", "password": PASSWORD})
    assert signed_in.status_code == 200 and signed_in.json()["user"]["team_id"] == 1
    assert signed_in.json()["user"]["role"] == "response_team"
