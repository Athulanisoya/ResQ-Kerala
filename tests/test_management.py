"""Administration keeps access scoped, audited and operational counts separate."""
import pytest
from sqlalchemy import select
from backend.tests.test_auth import api, synthetic_password_hash
from test_web import clients
from backend.models import Incident, Role, Team, TokenSession, User
from backend.models.admin_audit import AdminChange
from backend.models.community import DonationCampaign, DonationPledge
from backend.models.operations import ReliefRequest as OperationsRequest
from backend.models.relief import ReliefRequest as VidyaRequest
from backend.models.shelter import Shelter

BASE = "/api/management"

def test_account_access_control_session_revocation_and_audit(api):
    admin = api.headers("admin")
    citizen = api.headers("citizen")
    assert api.client.get(BASE + "/users", headers=citizen).status_code == 403
    for payload in ({"role": "citizen", "team_id": None, "active": True},
                    {"role": "admin", "team_id": None, "active": False}):
        assert api.client.patch(f"{BASE}/users/{api.users['admin']}", headers=admin, json=payload).status_code == 409
    assert api.client.patch(f"{BASE}/users/{api.users['citizen']}", headers=citizen,
                            json={"role": "admin", "team_id": None, "active": True}).status_code == 403
    invalid = api.client.patch(f"{BASE}/users/{api.users['citizen']}", headers=admin,
                               json={"role": "response_team", "team_id": None, "active": True})
    assert invalid.status_code == 422
    team = api.client.post(BASE + "/teams", headers=admin, json={"name": "East field", "team_type": "Investigation"})
    assert team.status_code == 201, team.text
    changed = api.client.patch(f"{BASE}/users/{api.users['citizen']}", headers=admin,
                               json={"role": "response_team", "team_id": team.json()["id"], "active": True})
    assert changed.status_code == 200 and changed.json()["role"] == "response_team"
    assert api.client.get("/api/users/me", headers=citizen).status_code == 401
    with api.sessions() as db:
        assert db.get(User, api.users["citizen"]).team_id == team.json()["id"]
        assert db.scalar(select(AdminChange).where(AdminChange.target_kind == "user")) is not None
        assert db.scalar(select(TokenSession).where(TokenSession.user_id == api.users["citizen"])).revoked_at is not None

def test_team_lifecycle_does_not_discard_active_work(api):
    admin = api.headers("admin")
    result = api.client.post(BASE + "/teams", headers=admin, json={"name": "River rescue", "team_type": "Rescue"})
    team_id = result.json()["id"]
    assert api.client.post(BASE + "/teams", headers=admin, json={"name": "river rescue", "team_type": "Rescue"}).status_code == 409
    with api.sessions() as db:
        incident = Incident(report_reference="RESQ ADMIN LIFE", user_id=api.users["citizen"],
                            location="Kochi", message="Test flood", status="ASSIGNED", assigned_team_id=team_id)
        db.add(incident); db.commit(); incident_id = incident.id
    path = f"{BASE}/teams/{team_id}"
    assert api.client.patch(path, headers=admin, json={"name": "River rescue", "status": "OFFLINE"}).status_code == 409
    with api.sessions() as db:
        db.get(Incident, incident_id).status = "RESOLVED"; db.commit()
    assert api.client.patch(path, headers=admin, json={"name": "River rescue", "status": "OFFLINE"}).status_code == 200
    assert api.client.patch(path, headers=admin, json={"name": "River rescue", "status": "AVAILABLE"}).status_code == 200

def test_reports_keep_relief_items_and_donation_units_separate(api):
    admin = api.headers("admin")
    with api.sessions() as db:
        inc = Incident(report_reference="RESQ REPORT COUNTS", user_id=api.users["citizen"],
                       location="Kochi", message="Synthetic flood", status="SUBMITTED")
        db.add(inc); db.flush()
        db.add(OperationsRequest(incident_id=inc.id, created_by_user_id=api.users["citizen"], kind="SUPPLIES", status="PENDING"))
        db.add_all([VidyaRequest(incident_id=inc.id, item="FOOD", quantity=5, fulfilled=2, created_by=api.users["citizen"]),
                    VidyaRequest(incident_id=inc.id, item="WATER", quantity=7, fulfilled=3, created_by=api.users["citizen"]),
                    Shelter(name="Synthetic shelter", capacity=20, occupied=4, status="OPEN")])
        campaign = DonationCampaign(title="Synthetic supplies", description="Demo only", created_by=api.users["admin"])
        db.add(campaign); db.flush()
        db.add_all([DonationPledge(campaign_id=campaign.id, donor_id=api.users["citizen"], kind="SUPPLIES", description="Water", quantity=3, unit="litres", status="PENDING"),
                    DonationPledge(campaign_id=campaign.id, donor_id=api.users["citizen"], kind="SUPPLIES", description="Food", quantity=2, unit="packets", status="RECEIVED")])
        db.commit()
    assert api.client.get(BASE + "/reports", headers=api.headers("response_team")).status_code == 403
    response = api.client.get(BASE + "/reports", headers=admin)
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["incidents_by_status"]["SUBMITTED"] == 1
    assert report["operations_relief_by_status"]["PENDING"] == 1
    assert {row["item"]: row["requested"] for row in report["item_relief"]} == {"FOOD": 5, "WATER": 7}
    assert report["shelters"] == {"count": 1, "capacity": 20, "occupied": 4}
    assert {(row["unit"], row["status"]) for row in report["donations"]} == {("litres", "PENDING"), ("packets", "RECEIVED")}


def test_admin_management_htmx_page_and_team_creation(clients):
    from test_web import login, post
    citizen, administrator, _ = clients
    login(citizen, "citizen"); login(administrator, "admin")
    assert citizen.get("/management").status_code == 403
    page = administrator.get("/management")
    assert page.status_code == 200 and "Aggregate reports" in page.text
    result = post(administrator, "/ui/management/teams", name="Synthetic investigation team", team_type="Investigation")
    assert result.status_code == 200 and result.headers["HX-Redirect"] == "/management"
    assert "Synthetic investigation team" in administrator.get("/management").text
