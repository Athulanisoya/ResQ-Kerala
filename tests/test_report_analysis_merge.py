"""Keep the incoming report snapshots alongside Athul's existing workflows."""

from datetime import datetime
import socket

from sqlalchemy import create_engine, event, select, text
from sqlalchemy.exc import SQLAlchemyError

from backend.tests.test_auth import TEST_PASSWORD, api, synthetic_password_hash
from backend.ai.summarizer import summarize_report
from backend.database.migrations import migrate_incident_summaries
from backend.models import Incident, IncidentStatusHistory, LocationAnalysis, Team, User
from backend.models.communication import Notification
from backend.models.incident_summary import IncidentSummary
from backend.models.operations import IncidentTask, IncidentTaskEvent
from backend.models.report_analysis import ReportAnalysis


REPORT = {
    "message": "Water entered our home. No one is injured. We need boat rescue.",
    "location": "Aluva", "people_affected": 4, "help_required": "Boat rescue",
    "disaster_type": "Flood",
}


def submit(api):
    result = api.client.post("/api/incidents/", headers=api.headers("citizen"), json=REPORT)
    assert result.status_code == 201, result.text
    return result.json()["id"]


def test_submission_retains_snapshots_local_checks_notifications_and_task_workflow(api):
    incident_id = submit(api)
    path = f"/api/incidents/{incident_id}/analysis"
    result = api.client.get(path, headers=api.headers("citizen"))
    assert result.status_code == 200, result.text
    snapshot = result.json()
    assert snapshot["incident_id"] == incident_id
    assert snapshot["summary_is_provisional"] is True
    assert snapshot["requires_manual_review"] is True
    assert "No one is injured." in snapshot["summary"]
    assert "Aluva" in snapshot["summary"] and "4" in snapshot["summary"]
    assert snapshot["created_at"]

    with api.sessions() as db:
        incident = db.get(Incident, incident_id)
        assert {key: getattr(incident, key) for key in REPORT} == REPORT
        assert incident.status == "SUBMITTED"
        assert len(db.scalars(select(ReportAnalysis)).all()) == 1
        assert len(db.scalars(select(IncidentSummary)).all()) == 1
        assert len(db.scalars(select(LocationAnalysis)).all()) == 1
        assert len(db.scalars(select(IncidentStatusHistory)).all()) == 1
        assert db.scalar(select(Notification).where(
            Notification.incident_id == incident_id,
            Notification.user_id == api.users["citizen"],
            Notification.title == "Report submitted",
        )) is not None
        team = Team(name="Merge regression rescue team", team_type="Rescue", status="AVAILABLE")
        db.add(team)
        db.flush()
        db.get(User, api.users["response_team"]).team_id = team.id
        db.commit()
        team_id = team.id

    verified = api.client.patch(f"/api/incidents/{incident_id}/status",
        headers=api.headers("admin"), json={"status": "VERIFIED"})
    assert verified.status_code == 200, verified.text
    assigned = api.client.post("/api/incidents/admin/assign-team", headers=api.headers("admin"),
        json={"incident_id": incident_id, "team_id": team_id})
    assert assigned.status_code == 200, assigned.text
    accepted = api.client.post(f"/api/operations/incidents/{incident_id}/accept",
        headers=api.headers("response_team"), json={})
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "TASK_ACCEPTED"
    with api.sessions() as db:
        incident = db.get(Incident, incident_id)
        assert {key: getattr(incident, key) for key in REPORT} == REPORT
        task = db.scalar(select(IncidentTask).where(IncidentTask.incident_id == incident_id))
        assert task is not None
        assert db.scalar(select(IncidentTaskEvent).where(
            IncidentTaskEvent.task_id == task.id,
            IncidentTaskEvent.status == "TASK_ACCEPTED",
        )) is not None
    assert api.client.get(path, headers=api.headers("citizen")).json() == snapshot
    # The administrator's reviewed assessment remains a separate resource.
    assessment = api.client.get(f"/api/admin/incidents/{incident_id}/analysis", headers=api.headers("admin"))
    assert assessment.status_code == 200 and assessment.json() is None


def test_snapshot_access_follows_incident_ownership_and_assignment(api):
    incident_id = submit(api)
    path = f"/api/incidents/{incident_id}/analysis"
    assert api.client.get(path).status_code == 401
    assert api.client.get(path, headers=api.headers("citizen")).status_code == 200
    assert api.client.get(path, headers=api.headers("admin")).status_code == 200
    assert api.client.get(path, headers=api.headers("response_team")).status_code == 403
    stranger = api.client.post("/api/auth/register", json={
        "full_name": "Other citizen", "email": "snapshot-stranger@example.com", "password": TEST_PASSWORD,
    })
    assert stranger.status_code == 201, stranger.text
    headers = {"Authorization": f"Bearer {stranger.json()['access_token']}"}
    assert api.client.get(path, headers=headers).status_code == 403
    with api.sessions() as db:
        team = Team(name="Assigned snapshot readers", team_type="Rescue")
        db.add(team)
        db.flush()
        db.get(User, api.users["response_team"]).team_id = team.id
        db.get(Incident, incident_id).assigned_team_id = team.id
        db.commit()
    assert api.client.get(path, headers=api.headers("response_team")).status_code == 200


def test_latest_snapshot_orders_by_timestamp_then_id(api):
    incident_id = submit(api)
    with api.sessions() as db:
        db.add_all([
            ReportAnalysis(incident_id=incident_id, summary="Same-time older identifier",
                           created_at=datetime(2040, 1, 1)),
            ReportAnalysis(incident_id=incident_id, summary="Older time, later identifier",
                           created_at=datetime(2039, 1, 1)),
            ReportAnalysis(incident_id=incident_id, summary="Expected latest snapshot",
                           summary_is_provisional=False, requires_manual_review=False,
                           created_at=datetime(2040, 1, 1)),
            ReportAnalysis(incident_id=incident_id, summary="Largest identifier, oldest time",
                           created_at=datetime(2038, 1, 1)),
        ])
        db.commit()
    result = api.client.get(f"/api/incidents/{incident_id}/analysis", headers=api.headers("citizen"))
    assert result.status_code == 200, result.text
    assert result.json()["summary"] == "Expected latest snapshot"
    assert result.json()["summary_is_provisional"] is False
    assert result.json()["requires_manual_review"] is False


def test_missing_snapshot_and_missing_incident_are_explicit(api):
    with api.sessions() as db:
        incident = Incident(report_reference="RESQ LEGACY NO SNAPSHOT", user_id=api.users["citizen"],
                            message="An old unmodified report", location="Aluva")
        db.add(incident)
        db.commit()
        incident_id = incident.id
    missing = api.client.get(f"/api/incidents/{incident_id}/analysis", headers=api.headers("citizen"))
    assert missing.status_code == 404 and "Analysis not found" in missing.json()["detail"]
    absent = api.client.get("/api/incidents/999999/analysis", headers=api.headers("admin"))
    assert absent.status_code == 404 and absent.json()["detail"] == "Incident not found"


def test_snapshot_storage_failure_rolls_back_all_submission_records(api):
    def fail_insert(_mapper, _connection, _target):
        raise SQLAlchemyError("Synthetic snapshot persistence failure")

    event.listen(ReportAnalysis, "before_insert", fail_insert)
    try:
        response = api.client.post("/api/incidents/", headers=api.headers("citizen"), json=REPORT)
        assert response.status_code == 503
    finally:
        event.remove(ReportAnalysis, "before_insert", fail_insert)
    with api.sessions() as db:
        for model in (Incident, ReportAnalysis, IncidentStatusHistory, IncidentSummary, LocationAnalysis, Notification):
            assert db.scalars(select(model)).all() == []


def test_compatibility_summarizer_works_without_keys_or_provider_requests(monkeypatch):
    def no_network(*_args, **_kwargs):
        raise AssertionError("Citizen summary snapshots must remain local")

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(socket.socket, "connect", no_network)
    result = summarize_report(REPORT["message"])
    assert result["is_provisional"] is True and result["requires_manual_review"] is True
    assert "No one is injured." in result["summary"]
    assert "boat rescue" in result["summary"]


def test_legacy_summary_migration_preserves_records_timestamps_and_is_idempotent():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        with engine.begin() as connection:
            connection.execute(text("""CREATE TABLE incident_reports (
                id INTEGER PRIMARY KEY, message TEXT NOT NULL, summary TEXT,
                summary_is_provisional BOOLEAN, requires_manual_review BOOLEAN)"""))
            connection.execute(text("""CREATE TABLE report_analysis (
                id INTEGER PRIMARY KEY, incident_id INTEGER NOT NULL, summary TEXT,
                summary_is_provisional BOOLEAN NOT NULL, requires_manual_review BOOLEAN NOT NULL,
                created_at DATETIME NOT NULL)"""))
            connection.execute(text("""INSERT INTO incident_reports VALUES
                (1, 'Original first report', 'Already migrated', 1, 1),
                (2, 'Original second report', 'No one was injured.', NULL, NULL),
                (3, 'Original third report', NULL, 1, 1),
                (4, 'Original fourth report', 'Reviewed legacy text', 0, 0)"""))
            connection.execute(text("""INSERT INTO report_analysis VALUES
                (1, 1, 'Already migrated', 0, 0, '2020-01-01 00:00:00')"""))
            before = connection.execute(text("SELECT * FROM incident_reports ORDER BY id")).all()
            migrate_incident_summaries(connection)
            first = connection.execute(text("SELECT * FROM report_analysis ORDER BY incident_id")).mappings().all()
            migrate_incident_summaries(connection)
            second = connection.execute(text("SELECT * FROM report_analysis ORDER BY incident_id")).mappings().all()
            assert first == second and len(first) == 3
            assert first[0]["created_at"] == "2020-01-01 00:00:00"
            assert not first[0]["summary_is_provisional"] and not first[0]["requires_manual_review"]
            assert first[1]["summary"] == "No one was injured."
            assert first[1]["summary_is_provisional"] and first[1]["requires_manual_review"]
            assert datetime.fromisoformat(first[1]["created_at"])
            assert not first[2]["summary_is_provisional"] and not first[2]["requires_manual_review"]
            assert datetime.fromisoformat(first[2]["created_at"])
            assert connection.execute(text("SELECT * FROM incident_reports ORDER BY id")).all() == before
    finally:
        engine.dispose()


def test_summary_migration_without_legacy_columns_is_a_noop():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE incident_reports (id INTEGER PRIMARY KEY, message TEXT NOT NULL)"))
            connection.execute(text("CREATE TABLE report_analysis (id INTEGER PRIMARY KEY, summary TEXT)"))
            connection.execute(text("INSERT INTO incident_reports VALUES (1, 'Original report')"))
            connection.execute(text("INSERT INTO report_analysis VALUES (1, 'Retained snapshot')"))
            migrate_incident_summaries(connection)
            assert connection.execute(text("SELECT * FROM incident_reports")).all() == [(1, "Original report")]
            assert connection.execute(text("SELECT * FROM report_analysis")).all() == [(1, "Retained snapshot")]
    finally:
        engine.dispose()
