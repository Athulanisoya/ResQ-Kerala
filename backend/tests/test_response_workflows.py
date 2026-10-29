"""Response-team state transitions and rescue-to-relief handoff checks."""

import pytest
from sqlalchemy import event
from sqlalchemy.exc import SQLAlchemyError

from .test_auth import api, synthetic_password_hash
from .test_workflows import assign, review, submit, workflow
from backend.models import Incident, IncidentStatusHistory, Team
from backend.models.relief import ReliefRequest


def accept(api, report_id, role="response_team"):
    return api.client.post(
        f"/api/teams/incidents/{report_id}/accept", headers=api.headers(role),
    )


def progress(api, report_id, status, role="response_team"):
    return api.client.patch(
        f"/api/incidents/{report_id}/progress", headers=api.headers(role),
        json={"status": status, "note": f"Moving task to {status}"},
    )


def assigned_report(api, team_id=None):
    report_id = submit(api).json()["id"]
    assert review(api, report_id).status_code == 200
    assert assign(api, report_id, team_id).status_code == 200
    return report_id


def start_task(api, report_id, role="response_team"):
    assert accept(api, report_id, role).status_code == 200
    assert progress(api, report_id, "EN_ROUTE", role).status_code == 200
    assert progress(api, report_id, "IN_PROGRESS", role).status_code == 200


def add_request(api, report_id, fulfilled=0):
    with api.sessions() as db:
        request = ReliefRequest(
            incident_id=report_id, item="WATER", quantity=5,
            fulfilled=fulfilled, created_by=api.users["citizen"],
        )
        db.add(request)
        db.commit()
        return request.id


def test_response_progress_requires_acceptance_and_order(workflow):
    api = workflow
    report_id = assigned_report(api)
    for state in ("EN_ROUTE", "IN_PROGRESS", "RESCUE_COMPLETED", "RESOLVED"):
        assert progress(api, report_id, state).status_code == 409
    assert accept(api, report_id).status_code == 200
    assert accept(api, report_id).status_code == 409
    assert progress(api, report_id, "IN_PROGRESS").status_code == 409
    assert progress(api, report_id, "EN_ROUTE").status_code == 200
    assert progress(api, report_id, "IN_PROGRESS").status_code == 200
    assert progress(api, report_id, "RESOLVED").status_code == 409
    assert progress(api, report_id, "RESCUE_COMPLETED").status_code == 200
    with api.sessions() as db:
        assert db.get(Team, api.team_id).status == "BUSY"
    history = api.client.get(
        f"/api/incidents/{report_id}/history", headers=api.headers("citizen"),
    ).json()
    assert [row["status"] for row in history] == [
        "SUBMITTED", "VERIFIED", "ASSIGNED", "ACCEPTED", "EN_ROUTE",
        "IN_PROGRESS", "RESCUE_COMPLETED",
    ]


@pytest.mark.parametrize("role", ["citizen", "admin", "other_team"])
def test_only_assigned_response_team_can_accept_or_progress(workflow, role):
    api = workflow
    report_id = assigned_report(api)
    assert accept(api, report_id, role).status_code == 403
    assert progress(api, report_id, "EN_ROUTE", role).status_code == 403
    with api.sessions() as db:
        assert db.get(Incident, report_id).status == "ASSIGNED"


def test_resolving_relief_releases_team_for_another_incident(workflow):
    api = workflow
    report_id = assigned_report(api, api.other_team_id)
    start_task(api, report_id, "other_team")
    assert progress(api, report_id, "RESCUE_COMPLETED", "other_team").status_code == 409
    assert progress(api, report_id, "RESOLVED", "other_team").status_code == 409
    request_id = add_request(api, report_id)
    assert progress(api, report_id, "RESOLVED", "other_team").status_code == 409
    with api.sessions() as db:
        assert db.get(Team, api.other_team_id).status == "BUSY"
        db.get(ReliefRequest, request_id).fulfilled = 5
        db.commit()
    result = progress(api, report_id, "RESOLVED", "other_team")
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "RESOLVED"
    with api.sessions() as db:
        assert db.get(Team, api.other_team_id).status == "AVAILABLE"
    next_report = submit(api).json()["id"]
    assert review(api, next_report).status_code == 200
    assert assign(api, next_report, api.other_team_id).status_code == 200


def test_rescue_handoff_swaps_access_and_team_availability(workflow):
    api = workflow
    report_id = assigned_report(api)
    start_task(api, report_id)
    handoff_url = f"/api/incidents/{report_id}/relief-handoff"
    data = {"team_id": api.other_team_id, "note": "Rescue finished; deliver supplies"}
    assert api.client.post(handoff_url, headers=api.headers("admin"), json=data).status_code == 409
    assert progress(api, report_id, "RESCUE_COMPLETED").status_code == 200
    assert api.client.post(handoff_url, headers=api.headers("admin"), json=data).status_code == 409
    add_request(api, report_id)
    for role in ("citizen", "response_team", "other_team"):
        assert api.client.post(handoff_url, headers=api.headers(role), json=data).status_code == 403
    result = api.client.post(handoff_url, headers=api.headers("admin"), json=data)
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "ASSIGNED"
    assert result.json()["assigned_team_id"] == api.other_team_id
    with api.sessions() as db:
        assert db.get(Team, api.team_id).status == "AVAILABLE"
        assert db.get(Team, api.other_team_id).status == "BUSY"
    assert accept(api, report_id).status_code == 403
    assert accept(api, report_id, "other_team").status_code == 200


def test_failed_completion_does_not_release_team(workflow):
    api = workflow
    report_id = assigned_report(api, api.other_team_id)
    start_task(api, report_id, "other_team")
    add_request(api, report_id, fulfilled=5)

    def fail_completion_history(_mapper, _connection, history):
        if history.status == "RESOLVED":
            raise SQLAlchemyError("Synthetic completion history failure")

    event.listen(IncidentStatusHistory, "before_insert", fail_completion_history)
    try:
        assert progress(api, report_id, "RESOLVED", "other_team").status_code == 503
    finally:
        event.remove(IncidentStatusHistory, "before_insert", fail_completion_history)
    with api.sessions() as db:
        assert db.get(Incident, report_id).status == "IN_PROGRESS"
        assert db.get(Team, api.other_team_id).status == "BUSY"


def test_shelter_team_cannot_accept_response_assignment(workflow):
    api = workflow
    with api.sessions() as db:
        db.get(Team, api.team_id).team_type = "Shelter"
        db.commit()
    report_id = assigned_report(api)
    assert accept(api, report_id).status_code == 403


def test_response_operations_report_missing_incidents(workflow):
    api = workflow
    assert accept(api, 999999).status_code == 404
    assert progress(api, 999999, "EN_ROUTE").status_code == 404
    assert api.client.post(
        "/api/incidents/999999/relief-handoff", headers=api.headers("admin"),
        json={"team_id": api.other_team_id, "note": "No such incident"},
    ).status_code == 404
