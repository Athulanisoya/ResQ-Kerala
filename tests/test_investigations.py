"""Admin analysis, investigation lifecycle, audit fields and access control."""
import os
from dataclasses import dataclass, field

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["ALLOW_SQLITE_FOR_TESTS"] = "true"
os.environ["JWT_SECRET"] = "synthetic-investigation-tests-only-secret-2026"

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database.connection import Base, get_db
from backend.models import Incident, Role, User
from backend.models.investigation import IncidentAnalysis, InvestigationReport
from backend.routers import auth, investigations
from backend.utils.security import hash_password


PASSWORD = "Synthetic-investigation-pass!2026"


@dataclass
class Harness:
    client: TestClient
    sessions: object
    users: dict
    incident_id: int
    tokens: dict = field(default_factory=dict)

    @property
    def path(self):
        return f"/api/admin/incidents/{self.incident_id}"

    def headers(self, user="admin"):
        if user not in self.tokens:
            response = self.client.post("/api/auth/login", json={
                "email": f"{user}@example.com", "password": PASSWORD,
            })
            assert response.status_code == 200, response.text
            self.tokens[user] = response.json()["access_token"]
        return {"Authorization": f"Bearer {self.tokens[user]}"}

    def start(self, user="admin", name="District review officer"):
        return self.client.post(f"{self.path}/investigation", headers=self.headers(user),
                                json={"assigned_to_name": name})


@pytest.fixture(scope="session")
def investigation_password_hash():
    return hash_password(PASSWORD)


@pytest.fixture
def api(investigation_password_hash):
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as db:
        accounts = {role.value: User(full_name=f"Test {role.value}", email=f"{role.value}@example.com",
                                    password_hash=investigation_password_hash, role=role) for role in Role}
        accounts["second_admin"] = User(full_name="Second administrator", email="second_admin@example.com",
                                        password_hash=investigation_password_hash, role=Role.ADMIN)
        db.add_all(accounts.values())
        db.flush()
        incident = Incident(report_reference="RESQ TEST INVESTIGATION", user_id=accounts["citizen"].id,
                            message="Water entered the ground floor; residents need help.", location="Kochi")
        db.add(incident)
        db.commit()
        ids = {name: account.id for name, account in accounts.items()}
        incident_id = incident.id

    app = FastAPI()
    app.include_router(auth.router)
    app.include_router(investigations.router)

    def override_database():
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = override_database
    try:
        with TestClient(app) as client:
            yield Harness(client, sessions, ids, incident_id)
    finally:
        engine.dispose()


def test_analysis_upsert_preserves_identity_and_records_reviewing_admin(api, capsys):
    headers = api.headers()
    assert api.client.get(f"{api.path}/analysis", headers=headers).json() is None
    response = api.client.put(f"{api.path}/analysis", headers=headers, json={
        "severity": "HIGH", "extracted_location": "  Kochi  ", "alert_match": "MATCH",
        "summary": "Flood warning corroborates the report.", "requires_investigation": True,
    })
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["extracted_location"] == "Kochi"
    assert saved["reviewed_by_user_id"] == api.users["admin"]
    assert saved["source"] == "MANUAL_DEMO"
    updated = api.client.put(f"{api.path}/analysis", headers=api.headers("second_admin"), json={
        "severity": "LOW", "extracted_location": " ", "summary": " ",
        "alert_match": "NO_MATCH", "requires_investigation": False, "source": "AI_MODULE",
    })
    assert updated.status_code == 200, updated.text
    result = updated.json()
    assert result["id"] == saved["id"] and result["created_at"] == saved["created_at"]
    assert (result["severity"], result["alert_match"], result["source"]) == ("LOW", "NO_MATCH", "AI_MODULE")
    assert result["summary"] is result["extracted_location"] is None
    assert result["requires_investigation"] is False
    assert result["reviewed_by_user_id"] == api.users["second_admin"]
    assert api.client.get(f"{api.path}/analysis", headers=headers).json() == result
    with api.sessions() as db:
        assert len(list(db.scalars(select(IncidentAnalysis)))) == 1
    assert "DEBUG:" not in capsys.readouterr().out


def test_start_reassignment_and_completion_preserve_audit_and_finality(api):
    assert api.client.get(f"{api.path}/investigation", headers=api.headers()).json() is None
    started = api.start()
    assert started.status_code == 201, started.text
    original = started.json()
    assert original["status"] == "IN_PROGRESS" and original["findings"] is None
    assert original["created_by_user_id"] == original["updated_by_user_id"] == api.users["admin"]

    reassigned = api.start(user="second_admin", name="  Field supervisor  ").json()
    assert reassigned["id"] == original["id"]
    assert reassigned["assigned_to_name"] == "Field supervisor"
    assert reassigned["created_by_user_id"] == api.users["admin"]
    assert reassigned["updated_by_user_id"] == api.users["second_admin"]

    path = f"/api/admin/incidents/investigations/{original['id']}"
    progress = api.client.patch(path, headers=api.headers(), json={
        "status": "IN_PROGRESS", "findings": "Residents contacted and location confirmed.", "action_taken": " ",
    })
    assert progress.status_code == 200 and progress.json()["action_taken"] is None
    completed = api.client.patch(path, headers=api.headers("second_admin"), json={
        "status": "COMPLETED", "findings": "All residents are safe and water has receded.",
        "action_taken": "Local response team confirmed the outcome.",
    })
    assert completed.status_code == 200, completed.text
    final = completed.json()
    assert final["status"] == "COMPLETED" and final["updated_by_user_id"] == api.users["second_admin"]
    assert final["created_at"] == original["created_at"]
    assert api.start(name="Another officer").status_code == 409
    for status in ("IN_PROGRESS", "COMPLETED"):
        blocked = api.client.patch(path, headers=api.headers(), json={
            "status": status, "findings": "Attempt to overwrite the completed findings.",
        })
        assert blocked.status_code == 409
    assert api.client.get(f"{api.path}/investigation", headers=api.headers()).json() == final
    with api.sessions() as db:
        assert len(list(db.scalars(select(InvestigationReport)))) == 1


@pytest.mark.parametrize("role", [None, "citizen", "response_team"])
def test_all_investigation_routes_require_an_authenticated_admin(api, role):
    headers = api.headers(role) if role else {}
    expected = 403 if role else 401
    calls = [
        ("GET", f"{api.path}/analysis", None),
        ("PUT", f"{api.path}/analysis", {"severity": "HIGH"}),
        ("GET", f"{api.path}/investigation", None),
        ("POST", f"{api.path}/investigation", {"assigned_to_name": "Review officer"}),
        ("PATCH", "/api/admin/incidents/investigations/1", {"status": "COMPLETED", "findings": "Residents are safe."}),
    ]
    for method, path, payload in calls:
        assert api.client.request(method, path, headers=headers, json=payload).status_code == expected


def test_unknown_incidents_and_investigations_return_not_found(api):
    headers = api.headers()
    for suffix in ("analysis", "investigation"):
        assert api.client.get(f"/api/admin/incidents/99999/{suffix}", headers=headers).status_code == 404
    assert api.client.put("/api/admin/incidents/99999/analysis", headers=headers, json={}).status_code == 404
    assert api.client.post("/api/admin/incidents/99999/investigation", headers=headers,
                           json={"assigned_to_name": "Review officer"}).status_code == 404
    assert api.client.patch("/api/admin/incidents/investigations/99999", headers=headers,
                            json={"status": "IN_PROGRESS", "findings": "Checking the incident."}).status_code == 404


@pytest.mark.parametrize("payload", [
    {"severity": "CRITICAL"}, {"alert_match": "UNKNOWN"}, {"source": "UNTRUSTED"},
    {"extracted_location": "x" * 256}, {"reviewed_by_user_id": 9999},
])
def test_invalid_analysis_inputs_cannot_create_a_record(api, payload):
    response = api.client.put(f"{api.path}/analysis", headers=api.headers(), json=payload)
    assert response.status_code == 422
    assert api.client.get(f"{api.path}/analysis", headers=api.headers()).json() is None


def test_investigation_validates_assignee_findings_and_supported_status(api):
    headers = api.headers()
    for payload in ({"assigned_to_name": " "}, {"assigned_to_name": "x" * 121},
                    {"assigned_to_name": "Officer", "created_by_user_id": 9999}):
        assert api.client.post(f"{api.path}/investigation", headers=headers, json=payload).status_code == 422
    started = api.start().json()
    path = f"/api/admin/incidents/investigations/{started['id']}"
    for changes in ({"status": "COMPLETE"}, {"status": "OPEN"}, {"findings": " "},
                    {"findings": "x" * 5001}, {"action_taken": "x" * 2001}, {"updated_by_user_id": 9999}):
        payload = {"status": "COMPLETED", "findings": "Residents are safe.", **changes}
        assert api.client.patch(path, headers=headers, json=payload).status_code == 422
    assert api.client.get(f"{api.path}/investigation", headers=headers).json() == started


def test_investigation_team_assignment_scopes_findings_and_revokes_on_reassignment(api, investigation_password_hash):
    from backend.models import Team
    with api.sessions() as db:
        selected = Team(name="Field investigation", team_type="Investigation")
        other = Team(name="Other investigation", team_type="Investigation")
        rescue = Team(name="Rescue", team_type="Rescue")
        db.add_all([selected, other, rescue]); db.flush()
        db.get(User, api.users["response_team"]).team_id = selected.id
        stranger = User(full_name="Other team", email="other-investigator@example.com", password_hash=investigation_password_hash,
                        role=Role.RESPONSE_TEAM, team_id=other.id)
        db.add(stranger); db.commit()
        selected_id, rescue_id = selected.id, rescue.id
    assignment_url = f"{api.path}/investigation/team"
    assert api.client.post(assignment_url, headers=api.headers("citizen"), json={"team_id": selected_id}).status_code == 403
    assert api.client.post(assignment_url, headers=api.headers(), json={"team_id": rescue_id}).status_code == 409
    result = api.client.post(assignment_url, headers=api.headers(), json={"team_id": selected_id})
    assert result.status_code == 200, result.text
    investigation_id = result.json()["id"]
    team = api.headers("response_team")
    outsider_login = api.client.post("/api/auth/login", json={"email": "other-investigator@example.com", "password": PASSWORD})
    outsider = {"Authorization": f"Bearer {outsider_login.json()['access_token']}"}
    assignments_url = "/api/admin/incidents/investigations/assigned"
    assigned = api.client.get(assignments_url, headers=team)
    assert assigned.status_code == 200 and assigned.json()[0]["location"] == "Kochi"
    assert api.client.get(assignments_url, headers=outsider).json() == []
    read_url = f"{api.path}/investigation"
    assert api.client.get(read_url, headers=team).status_code == 200
    assert api.client.get(read_url, headers=outsider).status_code == 403
    patch_url = f"/api/admin/incidents/investigations/{investigation_id}"
    payload = {"status": "IN_PROGRESS", "findings": "Location and affected residents confirmed."}
    assert api.client.patch(patch_url, headers=outsider, json=payload).status_code == 403
    assert api.client.patch(patch_url, headers=team, json=payload).status_code == 200
    assert api.start(name="Independent reviewer").status_code == 201
    assert api.client.patch(patch_url, headers=team, json=payload).status_code == 403
    assert api.client.get(assignments_url, headers=team).json() == []
