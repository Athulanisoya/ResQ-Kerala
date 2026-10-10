"""Combined Week 1 workflow and permissions using isolated synthetic accounts."""
import pytest
from sqlalchemy import event, select
from sqlalchemy.exc import SQLAlchemyError

from .test_auth import TEST_PASSWORD, api, synthetic_password_hash
from backend.models import Incident, IncidentStatusHistory, Role, Team, User


@pytest.fixture
def workflow(api, synthetic_password_hash):
    with api.sessions() as db:
        team = Team(name="Synthetic Rescue Team", team_type="Rescue")
        other_team = Team(name="Other Synthetic Team", team_type="Relief")
        db.add_all([team, other_team])
        db.flush()
        db.get(User, api.users["response_team"]).team_id = team.id
        other_citizen = User(full_name="Other Citizen", email="other_citizen@example.com",
                             role=Role.CITIZEN, password_hash=synthetic_password_hash)
        other_member = User(full_name="Other Team Member", email="other_team@example.com",
                            role=Role.RESPONSE_TEAM, team_id=other_team.id,
                            password_hash=synthetic_password_hash)
        db.add_all([other_citizen, other_member])
        db.commit()
        api.team_id, api.other_team_id = team.id, other_team.id
        api.users["other_citizen"] = other_citizen.id
        api.users["other_team"] = other_member.id
    return api


def submit(api, **changes):
    return api.client.post("/api/incidents/", headers=api.headers("citizen"), json={
        "message": "Water entered our house; we need help.", "location": "Kochi",
        "people_affected": 2, "help_required": "Rescue", "disaster_type": "Flood", **changes,
    })


def review(api, report_id, status="VERIFIED", **changes):
    return api.client.patch(f"/api/incidents/{report_id}/status", headers=api.headers("admin"),
                             json={"status": status, **changes})


def assign(api, report_id, team_id=None):
    return api.client.post("/api/admin/assign-team", headers=api.headers("admin"),
                            json={"incident_id": report_id, "team_id": team_id or api.team_id})


def test_submission_details_and_history(workflow):
    api = workflow
    response = submit(api)
    assert response.status_code == 201, response.text
    report = response.json()
    assert report["report_reference"].startswith("RESQ ")
    assert len(report["report_reference"]) <= 50
    assert report["status"] == "SUBMITTED" and report["assigned_team_id"] is None
    assert report["disaster_type"] == "Flood"
    assert report["user_id"] == api.users["citizen"]
    headers = api.headers("citizen")
    assert api.client.get(f"/api/incidents/{report['id']}", headers=headers).json() == report
    assert api.client.get("/api/incidents/", headers=headers).json() == [report]
    assert api.client.get("/api/incidents/my", headers=headers).json() == [report]
    history = api.client.get(f"/api/incidents/{report['id']}/history", headers=headers).json()
    assert [item["status"] for item in history] == ["SUBMITTED"]


def test_reports_belong_to_authenticated_user_and_headers_cannot_spoof(workflow):
    api = workflow
    report = submit(api).json()
    headers = {**api.headers("other_citizen"), "X-User-Id": str(api.users["citizen"])}
    assert api.client.get("/api/incidents/", headers=headers).json() == []
    for suffix in ("", "/history", "/status"):
        assert api.client.get(f"/api/incidents/{report['id']}{suffix}", headers=headers).status_code == 403
    assert api.client.get("/api/incidents/", headers={"X-User-Id": "1"}).status_code == 401
    assert api.client.post("/api/incidents/", headers={"X-User-Id": "1"}, json={
        "message": "This request has no bearer token", "location": "Kochi",
    }).status_code == 401


def test_complete_week1_review_assignment_and_tracking(workflow):
    api = workflow
    report_id = submit(api).json()["id"]
    assert api.client.get("/api/teams/assignments", headers=api.headers("response_team")).json() == []
    assert review(api, report_id, "UNDER_REVIEW", note="Location checked").status_code == 200
    assert review(api, report_id, note="Report verified").status_code == 200
    result = assign(api, report_id)
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "ASSIGNED"
    assert result.json()["assigned_team_id"] == api.team_id
    reports = api.client.get("/api/admin/incidents", headers=api.headers("admin")).json()
    assert [item["id"] for item in reports] == [report_id]
    teams = api.client.get("/api/teams", headers=api.headers("admin")).json()
    assert next(item for item in teams if item["id"] == api.team_id)["available"] is False
    assigned = api.client.get("/api/teams/assignments", headers=api.headers("response_team")).json()
    assert [item["id"] for item in assigned] == [report_id]
    for role in ("citizen", "admin", "response_team"):
        headers = api.headers(role)
        assert api.client.get(f"/api/incidents/{report_id}", headers=headers).status_code == 200
        assert api.client.get(f"/api/incidents/{report_id}/status", headers=headers).json() == {
            "incident_id": report_id, "status": "ASSIGNED",
        }
        history = api.client.get(f"/api/incidents/{report_id}/history", headers=headers).json()
        assert [item["status"] for item in history] == ["SUBMITTED", "UNDER_REVIEW", "VERIFIED", "ASSIGNED"]
    assert api.client.get("/api/teams/assignments", headers=api.headers("other_team")).json() == []
    assert api.client.get(f"/api/incidents/{report_id}", headers=api.headers("other_team")).status_code == 403


@pytest.mark.parametrize("role", ["citizen", "response_team"])
def test_admin_actions_require_admin_role(workflow, role):
    api = workflow
    report_id = submit(api).json()["id"]
    headers = api.headers(role)
    assert api.client.get("/api/admin/incidents", headers=headers).status_code == 403
    assert api.client.get("/api/teams", headers=headers).status_code == 403
    assert api.client.patch(f"/api/incidents/{report_id}/status", headers=headers,
                            json={"status": "VERIFIED"}).status_code == 403
    assert api.client.post("/api/admin/assign-team", headers=headers,
                           json={"incident_id": report_id, "team_id": api.team_id}).status_code == 403


@pytest.mark.parametrize("role", ["admin", "response_team"])
def test_only_citizens_submit_and_list_their_reports(workflow, role):
    api = workflow
    headers = api.headers(role)
    assert api.client.post("/api/incidents/", headers=headers, json={
        "message": "Another flood report", "location": "Kochi",
    }).status_code == 403
    assert api.client.get("/api/incidents/", headers=headers).status_code == 403


def test_unassigned_team_cannot_view_report_or_change_status(workflow):
    api = workflow
    report_id = submit(api).json()["id"]
    headers = api.headers("response_team")
    assert api.client.get(f"/api/incidents/{report_id}", headers=headers).status_code == 403
    assert api.client.get(f"/api/incidents/{report_id}/history", headers=headers).status_code == 403
    assert api.client.patch(f"/api/incidents/{report_id}/status", headers=headers,
                            json={"status": "VERIFIED"}).status_code == 403


def test_invalid_review_transitions_and_later_week_statuses_rejected(workflow):
    api = workflow
    report_id = submit(api).json()["id"]
    assert review(api, report_id).status_code == 200
    assert review(api, report_id).status_code == 409
    assert review(api, report_id, "UNDER_REVIEW").status_code == 409
    for status in ("ASSIGNED", "IN_PROGRESS", "RESOLVED", "SUBMITTED"):
        assert review(api, report_id, status).status_code == 422
    assert assign(api, report_id).status_code == 200
    assert review(api, report_id).status_code == 409
    history = api.client.get(f"/api/incidents/{report_id}/history", headers=api.headers("citizen")).json()
    assert len(history) == 3


def test_assignment_requires_verified_report_and_available_team(workflow):
    api = workflow
    first = submit(api).json()["id"]
    second = submit(api).json()["id"]
    assert assign(api, first).status_code == 409
    assert review(api, first).status_code == 200
    assert assign(api, first, 999999).status_code == 404
    assert assign(api, first).status_code == 200
    assert assign(api, first, api.other_team_id).status_code == 409
    assert review(api, second).status_code == 200
    assert assign(api, second).status_code == 409
    second_report = api.client.get(f"/api/incidents/{second}", headers=api.headers("admin")).json()
    assert second_report["status"] == "VERIFIED" and second_report["assigned_team_id"] is None
    with api.sessions() as db:
        assert db.get(Team, api.other_team_id).available is True


@pytest.mark.parametrize("change", [
    {"message": "Bad"}, {"message": "     "}, {"location": " "},
    {"people_affected": -1}, {"people_affected": 100001}, {"disaster_type": " "},
    {"user_id": 999}, {"assigned_team_id": 1}, {"status": "VERIFIED"},
])
def test_invalid_request_is_rejected(workflow, change):
    assert submit(workflow, **change).status_code == 422
    with workflow.sessions() as db:
        assert list(db.scalars(select(Incident))) == []


def test_references_remain_unique_after_an_older_report_is_deleted(workflow):
    api = workflow
    first = submit(api).json()
    second = submit(api).json()
    with api.sessions() as db:
        db.query(IncidentStatusHistory).filter_by(incident_id=first["id"]).delete()
        db.delete(db.get(Incident, first["id"]))
        db.commit()
    third_response = submit(api)
    assert third_response.status_code == 201, third_response.text
    assert len({first["report_reference"], second["report_reference"],
                third_response.json()["report_reference"]}) == 3


def test_submission_rolls_back_report_if_initial_history_cannot_save(workflow):
    def fail_history(_mapper, _connection, _target):
        raise SQLAlchemyError("Synthetic history failure")

    event.listen(IncidentStatusHistory, "before_insert", fail_history)
    try:
        assert submit(workflow).status_code == 503
    finally:
        event.remove(IncidentStatusHistory, "before_insert", fail_history)
    with workflow.sessions() as db:
        assert list(db.scalars(select(Incident))) == []
        assert list(db.scalars(select(IncidentStatusHistory))) == []


def test_missing_reports_and_assignment_targets_return_404(workflow):
    api = workflow
    for suffix in ("", "/history", "/status"):
        assert api.client.get(f"/api/incidents/999999{suffix}", headers=api.headers("citizen")).status_code == 404
    assert review(api, 999999).status_code == 404
    assert assign(api, 999999).status_code == 404
