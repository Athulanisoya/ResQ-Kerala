"""Private updates, retained clarification replies, and final closure guards."""

import pytest
from sqlalchemy import event, select
from sqlalchemy.exc import SQLAlchemyError

from backend.tests.test_auth import api, synthetic_password_hash
from backend.models import Incident, IncidentStatusHistory, Role, Team, User
from backend.models.communication import ClarificationReply, IncidentClarification, Notification
from backend.services.communication_service import notify_incident


BASE = "/api/communication"


@pytest.fixture
def correspondence(api, synthetic_password_hash):
    with api.sessions() as db:
        team = Team(name="Correspondence rescue team", team_type="Rescue")
        inactive_admin = User(full_name="Inactive administrator", email="inactive-communication@example.com",
                              password_hash=synthetic_password_hash, role=Role.ADMIN, active=False)
        db.add_all([team, inactive_admin])
        db.flush()
        db.get(User, api.users["response_team"]).team_id = team.id
        incident = Incident(report_reference="RESQ COMMUNICATION TEST", user_id=api.users["citizen"],
                            message="Flood water is entering our home. Please send a rescue boat.",
                            location="Kochi", status="ASSIGNED", assigned_team_id=team.id)
        db.add(incident)
        db.commit()
        api.incident_id = incident.id
        api.team_id = team.id
        api.inactive_admin_id = inactive_admin.id
    other = api.client.post("/api/auth/register", json={
        "full_name": "Unrelated citizen", "email": "unrelated-communication@example.com",
        "password": "Unrelated-citizen-pass!2026",
    })
    assert other.status_code == 201, other.text
    api.other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}
    api.other_id = other.json()["user"]["id"]
    api.questions_url = f"{BASE}/incidents/{api.incident_id}/clarifications"
    api.close_url = f"{BASE}/incidents/{api.incident_id}/close"
    return api


def ask(api, question="How many people still need evacuation?", required=True):
    response = api.client.post(api.questions_url, headers=api.headers("admin"),
                               json={"question": question, "required": required})
    assert response.status_code == 201, response.text
    return response.json()


def notify(api, key="test-update"):
    with api.sessions() as db:
        records = notify_incident(db, db.get(Incident, api.incident_id), "Response update",
                                   "The assigned rescue team is on the way.", event_key=key)
        ids = {row.user_id: row.id for row in records}
        db.commit()
    return ids


def test_notifications_only_reach_owner_admin_and_current_assigned_team(correspondence):
    api = correspondence
    ids = notify(api)
    assert set(ids) == set(api.users.values())
    assert api.inactive_admin_id not in ids and api.other_id not in ids
    for role in api.users:
        response = api.client.get(f"{BASE}/notifications", headers=api.headers(role))
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["unread_count"] == 1
        assert [row["id"] for row in body["notifications"]] == [ids[api.users[role]]]
        row = body["notifications"][0]
        assert row["created_at"].endswith("+00:00")
        assert "user_id" not in row and "event_key" not in row and "email" not in row
    unrelated = api.client.get(f"{BASE}/notifications", headers=api.other_headers).json()
    assert unrelated == {"unread_count": 0, "notifications": [], "next_before_id": None}
    assert api.client.get(f"{BASE}/notifications").status_code == 401


def test_explicit_support_team_only_receives_its_relief_event_and_gets_workspace_link(correspondence, synthetic_password_hash):
    api = correspondence
    with api.sessions() as db:
        support = Team(name="Explicit relief support", team_type="Relief")
        unrelated = Team(name="Unrelated relief team", team_type="Relief")
        db.add_all([support, unrelated])
        db.flush()
        member = User(full_name="Relief support member", email="support-update@example.com",
                      role=Role.RESPONSE_TEAM, password_hash=synthetic_password_hash, team_id=support.id)
        inactive = User(full_name="Inactive support member", email="inactive-support-update@example.com",
                        role=Role.RESPONSE_TEAM, password_hash=synthetic_password_hash, team_id=support.id, active=False)
        stranger = User(full_name="Other relief member", email="stranger-update@example.com",
                        role=Role.RESPONSE_TEAM, password_hash=synthetic_password_hash, team_id=unrelated.id)
        db.add_all([member, inactive, stranger])
        db.flush()
        member_id, inactive_id, stranger_id = member.id, inactive.id, stranger.id
        incident = db.get(Incident, api.incident_id)
        records = notify_incident(db, incident, "Relief assigned", "Deliver drinking water.",
                                  event_key="relief:77:assigned", extra_team_ids=(support.id,))
        assert {row.user_id for row in records} == {*api.users.values(), member_id}
        assert inactive_id not in {row.user_id for row in records}
        assert stranger_id not in {row.user_id for row in records}
        delivery = notify_incident(db, incident, "Relief delivery", "Drinking water delivered.",
                                   event_key="relief-delivery:77:recorded", extra_team_ids=(support.id,))
        assert member_id in {row.user_id for row in delivery}
        generic = notify_incident(db, incident, "Private clarification", "Please confirm your location.",
                                  event_key="clarification:4:requested")
        assert member_id not in {row.user_id for row in generic}
        db.commit()
        from backend.services.communication_service import list_notifications
        updates = list_notifications(db, member_id)
        assert len(updates["notifications"]) == 2
        assert all(row["target_url"] == "/operations" for row in updates["notifications"])
        owner_updates = list_notifications(db, api.users["citizen"])
        assert owner_updates["notifications"][0]["target_url"] == f"/reports/{api.incident_id}"
        assert list_notifications(db, stranger_id)["notifications"] == []


def test_notifications_read_is_private_idempotent_and_read_all_is_scoped(correspondence):
    api = correspondence
    ids = notify(api)
    owner_id = ids[api.users["citizen"]]
    path = f"{BASE}/notifications/{owner_id}/read"
    assert api.client.post(path, headers=api.headers("admin")).status_code == 404
    assert api.client.post(path, headers=api.other_headers).status_code == 404
    first = api.client.post(path, headers=api.headers("citizen"))
    second = api.client.patch(path, headers=api.headers("citizen"))
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json() and first.json()["is_read"] is True
    assert api.client.post(f"{BASE}/notifications/read-all", headers=api.headers("admin")).json() == {
        "updated_count": 1, "unread_count": 0}
    assert api.client.post(f"{BASE}/notifications/read-all", headers=api.headers("admin")).json()["updated_count"] == 0
    assert api.client.get(f"{BASE}/notifications", headers=api.headers("response_team")).json()["unread_count"] == 1


def test_notifications_are_bounded_and_cursor_does_not_leak_other_users(correspondence):
    api = correspondence
    for index in range(5):
        notify(api, f"page-{index}")
    first = api.client.get(f"{BASE}/notifications?limit=2", headers=api.headers("citizen")).json()
    second = api.client.get(f"{BASE}/notifications?limit=2&before_id={first['next_before_id']}",
                            headers=api.headers("citizen")).json()
    last = api.client.get(f"{BASE}/notifications?limit=2&before_id={second['next_before_id']}",
                          headers=api.headers("citizen")).json()
    rows = first["notifications"] + second["notifications"] + last["notifications"]
    assert len(rows) == len({row["id"] for row in rows}) == 5
    assert first["unread_count"] == 5 and last["next_before_id"] is None
    assert api.client.get(f"{BASE}/notifications?limit=101", headers=api.headers("citizen")).status_code == 422
    assert api.client.get(f"{BASE}/notifications?before_id=-1", headers=api.headers("citizen")).status_code == 422


def test_notification_helper_deduplicates_and_obeys_callers_rollback(correspondence):
    api = correspondence
    with api.sessions() as db:
        incident = db.get(Incident, api.incident_id)
        assert len(notify_incident(db, incident, "Progress", "Rescue is underway.", "stable")) == 3
        assert notify_incident(db, incident, "Progress", "Rescue is underway.", "stable") == []
        assert len(list(db.scalars(select(Notification)))) == 3
        db.rollback()
    with api.sessions() as db:
        assert list(db.scalars(select(Notification))) == []
    notify(api)
    notify(api)
    with api.sessions() as db:
        assert len(list(db.scalars(select(Notification)))) == 3


@pytest.mark.parametrize("role", ["citizen", "response_team"])
def test_only_admin_can_request_or_cancel_clarification(correspondence, role):
    api = correspondence
    response = api.client.post(api.questions_url, headers=api.headers(role), json={"question": "People affected?"})
    assert response.status_code == 403
    question = ask(api)
    assert api.client.post(f"{BASE}/clarifications/{question['id']}/cancel", headers=api.headers(role)).status_code == 403


def test_clarification_read_uses_incident_owner_admin_and_assigned_team_access(correspondence):
    api = correspondence
    question = ask(api)
    for role in api.users:
        response = api.client.get(api.questions_url, headers=api.headers(role))
        assert response.status_code == 200
        assert response.json() == [question]
    assert api.client.get(api.questions_url, headers=api.other_headers).status_code == 403
    assert api.client.get(api.questions_url).status_code == 401
    with api.sessions() as db:
        db.get(Incident, api.incident_id).assigned_team_id = None
        db.commit()
    assert api.client.get(api.questions_url, headers=api.headers("response_team")).status_code == 403


def test_only_owner_replies_and_original_report_is_immutable(correspondence):
    api = correspondence
    with api.sessions() as db:
        incident = db.get(Incident, api.incident_id)
        original = (incident.message, incident.location, incident.status, incident.updated_at)
    question = ask(api)
    path = f"{BASE}/clarifications/{question['id']}/reply"
    for headers in [api.headers("admin"), api.headers("response_team"), api.other_headers]:
        assert api.client.post(path, headers=headers, json={"message": "Three people."}).status_code == 403
    reply = api.client.post(path, headers=api.headers("citizen"), json={"message": "  Three people, including a child.  "})
    assert reply.status_code == 200, reply.text
    body = reply.json()
    assert body["status"] == "ANSWERED" and body["question"] == question["question"]
    assert body["replies"][0]["message"] == "Three people, including a child."
    assert body["asked_at"] and body["replied_at"] and len(body["replies"]) == 1
    with api.sessions() as db:
        incident = db.get(Incident, api.incident_id)
        assert (incident.message, incident.location, incident.status, incident.updated_at) == original
        assert [row.status for row in db.scalars(select(IncidentStatusHistory).order_by(IncidentStatusHistory.id))] == [
            "CLARIFICATION_REQUESTED", "CLARIFICATION_REPLIED"]


def test_reply_retry_is_idempotent_changed_reply_conflicts_and_retains_first(correspondence):
    api = correspondence
    question = ask(api)
    path = f"{BASE}/clarifications/{question['id']}/reply"
    first = api.client.post(path, headers=api.headers("citizen"), json={"message": "There are four people."})
    retry = api.client.post(path, headers=api.headers("citizen"), json={"message": "There are four people."})
    changed = api.client.post(path, headers=api.headers("citizen"), json={"message": "An edited answer."})
    assert first.status_code == retry.status_code == 200 and first.json() == retry.json()
    assert changed.status_code == 409
    with api.sessions() as db:
        replies = list(db.scalars(select(ClarificationReply)))
        assert len(replies) == 1 and replies[0].message == "There are four people."
        assert len(list(db.scalars(select(Notification)))) == 6
        assert len(list(db.scalars(select(IncidentStatusHistory)))) == 2


@pytest.mark.parametrize("payload", [{"question": "  "}, {"question": "x" * 1001},
                                      {"question": "Valid question", "asked_by_id": 1}])
def test_question_validation_rejects_empty_long_or_privileged_fields(correspondence, payload):
    api = correspondence
    assert api.client.post(api.questions_url, headers=api.headers("admin"), json=payload).status_code == 422
    with api.sessions() as db:
        assert list(db.scalars(select(IncidentClarification))) == []
        assert list(db.scalars(select(Notification))) == []


@pytest.mark.parametrize("message", [" ", "x" * 3001])
def test_reply_validation_preserves_pending_question(correspondence, message):
    api = correspondence
    question = ask(api)
    response = api.client.post(f"{BASE}/clarifications/{question['id']}/reply",
                               headers=api.headers("citizen"), json={"message": message})
    assert response.status_code == 422
    assert api.client.get(api.questions_url, headers=api.headers("citizen")).json()[0]["status"] == "OPEN"


def test_cancellation_is_retained_idempotent_and_blocks_reply(correspondence):
    api = correspondence
    question = ask(api)
    path = f"{BASE}/clarifications/{question['id']}/cancel"
    first = api.client.post(path, headers=api.headers("admin"))
    second = api.client.post(path, headers=api.headers("admin"))
    assert first.status_code == second.status_code == 200 and first.json() == second.json()
    assert first.json()["status"] == "CANCELLED" and first.json()["question"] == question["question"]
    assert api.client.post(f"{BASE}/clarifications/{question['id']}/reply", headers=api.headers("citizen"),
                           json={"message": "A delayed response."}).status_code == 409
    with api.sessions() as db:
        assert len(list(db.scalars(select(IncidentClarification)))) == 1
        assert len(list(db.scalars(select(Notification)))) == 6


def test_answered_question_cannot_be_cancelled(correspondence):
    api = correspondence
    question = ask(api)
    api.client.post(f"{BASE}/clarifications/{question['id']}/reply", headers=api.headers("citizen"),
                     json={"message": "Four people require help."})
    assert api.client.post(f"{BASE}/clarifications/{question['id']}/cancel", headers=api.headers("admin")).status_code == 409


@pytest.mark.parametrize("role", ["citizen", "response_team"])
def test_only_admin_can_finally_close_incident(correspondence, role):
    api = correspondence
    with api.sessions() as db:
        db.get(Incident, api.incident_id).status = "RESOLVED"
        db.commit()
    assert api.client.post(api.close_url, headers=api.headers(role), json={}).status_code == 403


def test_closure_requires_resolution_and_completed_relief(correspondence, monkeypatch):
    import backend.services.operations_service as operations
    api = correspondence
    assert api.client.post(api.close_url, headers=api.headers("admin"), json={}).status_code == 409
    with api.sessions() as db:
        db.get(Incident, api.incident_id).status = "RESOLVED"
        db.commit()
    monkeypatch.setattr(operations, "unfinished_relief", lambda _db, _id: True)
    response = api.client.post(api.close_url, headers=api.headers("admin"), json={})
    assert response.status_code == 409 and "relief" in response.json()["detail"]
    with api.sessions() as db:
        assert db.get(Incident, api.incident_id).status == "RESOLVED"
        assert list(db.scalars(select(Notification))) == []


def test_real_outstanding_relief_request_blocks_closure(correspondence):
    from backend.models.operations import ReliefRequest
    api = correspondence
    with api.sessions() as db:
        db.get(Incident, api.incident_id).status = "RESOLVED"
        request = ReliefRequest(incident_id=api.incident_id, created_by_user_id=api.users["citizen"],
                                kind="RESCUE_SUPPORT", status="PENDING")
        db.add(request)
        db.commit()
        request_id = request.id
    assert api.client.post(api.close_url, headers=api.headers("admin"), json={}).status_code == 409
    with api.sessions() as db:
        db.get(ReliefRequest, request_id).status = "COMPLETED"
        db.commit()
    assert api.client.post(api.close_url, headers=api.headers("admin"), json={}).status_code == 200


def test_required_questions_block_closure_until_cancelled_and_closed_history_is_retained(correspondence):
    api = correspondence
    required = ask(api)
    optional = ask(api, question="Can you provide any extra details?", required=False)
    with api.sessions() as db:
        db.get(Incident, api.incident_id).status = "RESOLVED"
        db.commit()
    blocked = api.client.post(api.close_url, headers=api.headers("admin"), json={})
    assert blocked.status_code == 409 and "clarifications" in blocked.json()["detail"]
    api.client.post(f"{BASE}/clarifications/{required['id']}/cancel", headers=api.headers("admin"))
    closed = api.client.post(api.close_url, headers=api.headers("admin"), json={"note": "All rescue work confirmed complete."})
    assert closed.status_code == 200, closed.text
    assert closed.json()["status"] == "CLOSED" and closed.json()["closed_at"].endswith("+00:00")
    assert api.client.post(api.close_url, headers=api.headers("admin"), json={}).status_code == 409
    assert api.client.post(api.questions_url, headers=api.headers("admin"), json={"question": "Another question?"}).status_code == 409
    assert api.client.post(f"{BASE}/clarifications/{optional['id']}/reply", headers=api.headers("citizen"),
                           json={"message": "Late extra details."}).status_code == 409
    rows = api.client.get(api.questions_url, headers=api.headers("citizen")).json()
    assert [row["id"] for row in rows] == [required["id"], optional["id"]]
    with api.sessions() as db:
        history = list(db.scalars(select(IncidentStatusHistory).where(IncidentStatusHistory.status == "CLOSED")))
        assert len(history) == 1 and history[0].note == "All rescue work confirmed complete."


def test_answering_required_question_allows_closure(correspondence):
    api = correspondence
    question = ask(api)
    assert api.client.post(f"{BASE}/clarifications/{question['id']}/reply", headers=api.headers("citizen"),
                           json={"message": "Everyone is now safe."}).status_code == 200
    with api.sessions() as db:
        db.get(Incident, api.incident_id).status = "RESOLVED"
        db.commit()
    assert api.client.post(api.close_url, headers=api.headers("admin"), json={}).status_code == 200


def test_retained_reply_receipt_can_be_retried_after_closure_without_new_correspondence(correspondence):
    api = correspondence
    question = ask(api)
    path = f"{BASE}/clarifications/{question['id']}/reply"
    answer = {"message": "Everyone is now safe."}
    first = api.client.post(path, headers=api.headers("citizen"), json=answer)
    assert first.status_code == 200
    with api.sessions() as db:
        db.get(Incident, api.incident_id).status = "RESOLVED"
        db.commit()
    assert api.client.post(api.close_url, headers=api.headers("admin"), json={}).status_code == 200
    retry = api.client.post(path, headers=api.headers("citizen"), json=answer)
    assert retry.status_code == 200 and retry.json() == first.json()
    assert api.client.post(path, headers=api.headers("citizen"), json={"message": "A different reply."}).status_code == 409
    with api.sessions() as db:
        assert len(list(db.scalars(select(ClarificationReply)))) == 1
        assert len(list(db.scalars(select(Notification)))) == 9
        assert len(list(db.scalars(select(IncidentStatusHistory)))) == 3


def test_storage_failure_rolls_back_question_history_and_notifications(correspondence):
    api = correspondence
    def fail_notification(_mapper, _connection, _target):
        raise SQLAlchemyError("Synthetic notification failure with confidential connection diagnostics")
    event.listen(Notification, "before_insert", fail_notification)
    try:
        response = api.client.post(api.questions_url, headers=api.headers("admin"), json={"question": "Please confirm the location?"})
        assert response.status_code == 503
        assert "confidential" not in response.text
    finally:
        event.remove(Notification, "before_insert", fail_notification)
    with api.sessions() as db:
        assert list(db.scalars(select(IncidentClarification))) == []
        assert list(db.scalars(select(IncidentStatusHistory))) == []
        assert list(db.scalars(select(Notification))) == []


def test_failed_reply_does_not_lose_pending_question_or_leak_notifications(correspondence):
    api = correspondence
    question = ask(api)
    def fail_reply(_mapper, _connection, _target):
        raise SQLAlchemyError("Synthetic reply failure")
    event.listen(ClarificationReply, "before_insert", fail_reply)
    try:
        response = api.client.post(f"{BASE}/clarifications/{question['id']}/reply", headers=api.headers("citizen"),
                                   json={"message": "Two people still require help."})
        assert response.status_code == 503
    finally:
        event.remove(ClarificationReply, "before_insert", fail_reply)
    with api.sessions() as db:
        assert db.get(IncidentClarification, question["id"]).status == "OPEN"
        assert list(db.scalars(select(ClarificationReply))) == []
        assert len(list(db.scalars(select(Notification)))) == 3
        assert len(list(db.scalars(select(IncidentStatusHistory)))) == 1


def test_failed_closure_rolls_back_final_status_history_and_notifications(correspondence):
    api = correspondence
    with api.sessions() as db:
        db.get(Incident, api.incident_id).status = "RESOLVED"
        db.commit()
    def fail_notification(_mapper, _connection, _target):
        raise SQLAlchemyError("Synthetic closure update failure")
    event.listen(Notification, "before_insert", fail_notification)
    try:
        response = api.client.post(api.close_url, headers=api.headers("admin"), json={})
        assert response.status_code == 503
    finally:
        event.remove(Notification, "before_insert", fail_notification)
    with api.sessions() as db:
        assert db.get(Incident, api.incident_id).status == "RESOLVED"
        assert list(db.scalars(select(IncidentStatusHistory))) == []
        assert list(db.scalars(select(Notification))) == []


@pytest.mark.parametrize("legacy", [False, True])
def test_both_close_routes_enforce_pending_vidya_relief_and_legacy_questions(correspondence, legacy):
    from backend.models.relief import ReliefRequest as VidyaRequest
    api = correspondence
    path = f"/api/incidents/{api.incident_id}/close" if legacy else api.close_url
    payload = {"reason": "All response work complete"} if legacy else {"note": "All response work complete"}
    assert api.client.post(path, headers=api.headers("citizen"), json=payload).status_code == 403
    assert api.client.post(path, headers=api.headers("admin"), json=payload).status_code == 409
    with api.sessions() as db:
        incident = db.get(Incident, api.incident_id)
        incident.status = "RESOLVED"
        request = VidyaRequest(incident_id=incident.id, item="FOOD", quantity=3, fulfilled=1,
                               created_by=api.users["citizen"])
        db.add(request); db.commit(); request_id = request.id
    blocked = api.client.post(path, headers=api.headers("admin"), json=payload)
    assert blocked.status_code == 409 and "relief" in blocked.json()["detail"]
    with api.sessions() as db:
        db.get(VidyaRequest, request_id).fulfilled = 3
        db.add(IncidentStatusHistory(incident_id=api.incident_id, status="AWAITING_CLARIFICATION",
                                     note="Clarification requested by admin: where?"))
        db.commit()
    blocked = api.client.post(path, headers=api.headers("admin"), json=payload)
    assert blocked.status_code == 409 and "clarification" in blocked.json()["detail"]
    with api.sessions() as db:
        db.add(IncidentStatusHistory(incident_id=api.incident_id, status="UNDER_REVIEW",
                                     note="Citizen clarification response: Safe now."))
        db.commit()
    closed = api.client.post(path, headers=api.headers("admin"), json=payload)
    assert closed.status_code == 200, closed.text
    with api.sessions() as db:
        assert db.get(Incident, api.incident_id).status == "CLOSED"
        assert len(list(db.scalars(select(IncidentStatusHistory).where(
            IncidentStatusHistory.incident_id == api.incident_id, IncidentStatusHistory.status == "CLOSED")))) == 1


def test_open_investigation_blocks_closure(correspondence):
    from backend.models.investigation import InvestigationReport
    api = correspondence
    with api.sessions() as db:
        db.get(Incident, api.incident_id).status = "RESOLVED"
        investigation = InvestigationReport(incident_id=api.incident_id, assigned_to_name="Reviewer", status="IN_PROGRESS",
                                            created_by_user_id=api.users["admin"], updated_by_user_id=api.users["admin"])
        db.add(investigation); db.commit(); investigation_id = investigation.id
    response = api.client.post(api.close_url, headers=api.headers("admin"), json={})
    assert response.status_code == 409 and "investigation" in response.json()["detail"]
    with api.sessions() as db:
        db.get(InvestigationReport, investigation_id).status = "COMPLETED"
        db.commit()
    assert api.client.post(api.close_url, headers=api.headers("admin"), json={}).status_code == 200


@pytest.mark.parametrize("reply_path", ["legacy", "canonical"])
def test_legacy_clarification_remains_visible_and_preserves_active_assignment(correspondence, reply_path):
    api = correspondence
    incident_path = f"/api/incidents/{api.incident_id}"
    with api.sessions() as db:
        db.get(Incident, api.incident_id).status = "IN_PROGRESS"
        db.commit()
    request = api.client.post(incident_path + "/clarification", headers=api.headers("admin"),
                              json={"message": "Is the road still passable?"})
    assert request.status_code == 200, request.text
    with api.sessions() as db:
        incident = db.get(Incident, api.incident_id)
        assert incident.status == "IN_PROGRESS" and incident.assigned_team_id == api.team_id
    questions = api.client.get(api.questions_url, headers=api.headers("citizen")).json()
    assert len(questions) == 1 and questions[0]["status"] == "OPEN"
    notifications = api.client.get(BASE + "/notifications", headers=api.headers("citizen")).json()["notifications"]
    assert any(item["title"] == "Clarification requested" for item in notifications)
    path = incident_path + "/clarification/respond" if reply_path == "legacy" else f"{BASE}/clarifications/{questions[0]['id']}/reply"
    assert api.client.post(path, headers=api.other_headers, json={"message": "Road is open."}).status_code == 403
    reply = api.client.post(path, headers=api.headers("citizen"), json={"message": "Road is open."})
    assert reply.status_code == 200, reply.text
    assert api.client.get(api.questions_url, headers=api.headers("citizen")).json()[0]["status"] == "ANSWERED"
    with api.sessions() as db:
        incident = db.get(Incident, api.incident_id)
        assert incident.status == "IN_PROGRESS" and incident.assigned_team_id == api.team_id
        incident.status = "RESOLVED"; db.commit()
    assert api.client.post(api.close_url, headers=api.headers("admin"), json={}).status_code == 200
