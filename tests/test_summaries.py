"""Grounded local extraction, summary persistence, and incident permissions."""

from types import SimpleNamespace

import pytest
from sqlalchemy import event, select
from sqlalchemy.exc import SQLAlchemyError

from backend.tests.test_auth import api, synthetic_password_hash
from backend.ai.report_summarizer import MAX_SUMMARY_LENGTH, input_hash, summarize_report
from backend.models import Incident, IncidentStatusHistory, Role, Team, User
from backend.models.incident_summary import IncidentSummary
from backend.models.investigation import IncidentAnalysis
from backend.services.summary_service import save_summary


def report(**changes):
    return SimpleNamespace(message="Water entered the house. No one is injured. We need evacuation.",
                           location="Kochi", people_affected=4, help_required="Boat evacuation",
                           disaster_type="Flood", **changes)


def test_extraction_uses_explicit_facts_and_preserves_negative_casualty_statement():
    incident = report()
    result = summarize_report(incident)
    assert "Reported location: Kochi." in result
    assert "People affected (reported): 4." in result
    assert "Help requested: Boat evacuation." in result
    assert "No one is injured." in result
    assert "We need evacuation." in result
    assert result == summarize_report(incident)
    assert len(result) <= MAX_SUMMARY_LENGTH


def test_late_urgent_sentence_survives_a_long_report():
    incident = report()
    incident.message = ("Rain continued near the road. " * 100
                        + "Two children are trapped upstairs and need rescue. No deaths have been reported.")
    result = summarize_report(incident)
    assert "Two children are trapped upstairs and need rescue." in result
    assert "No deaths have been reported." in result
    assert len(result) <= 1200


def test_line_wrap_cannot_separate_a_negation_from_its_statement():
    incident = report()
    incident.message = "No one was\ninjured. A child needs rescue. Evacuation is requested."
    result = summarize_report(incident)
    assert "No one was injured." in result
    assert "Report excerpts: injured." not in result


def test_multilingual_text_and_unknown_counts_are_not_invented(monkeypatch):
    import socket

    def prohibit_network(*_args, **_kwargs):
        raise AssertionError("Local extraction must not call a provider")

    monkeypatch.setattr(socket, "create_connection", prohibit_network)
    incident = report()
    incident.message = "വീട്ടിൽ വെള്ളം കയറി. കുട്ടികൾ കുടുങ്ങിയിരിക്കുന്നു. ആർക്കും പരിക്കില്ല."
    incident.people_affected = None
    incident.help_required = None
    result = summarize_report(incident)
    assert "കുട്ടികൾ കുടുങ്ങിയിരിക്കുന്നു." in result
    assert "ആർക്കും പരിക്കില്ല." in result
    assert "People affected" not in result and "Help requested" not in result
    assert "None" not in result


def test_long_single_sentence_selects_urgent_tail_without_overflow():
    incident = report()
    incident.message = " ".join(["rain along the road"] * 150) + "; two children are trapped upstairs and need rescue"
    result = summarize_report(incident)
    assert "two children are trapped upstairs and need rescue" in result
    assert len(result) <= 1200


def test_hash_records_all_input_fields_and_is_stable():
    incident = report()
    original = input_hash(incident)
    assert len(original) == 64 and original == input_hash(incident)
    incident.help_required = "Medical care"
    assert input_hash(incident) != original


@pytest.fixture
def legacy_report(api, synthetic_password_hash):
    with api.sessions() as db:
        team = Team(name="Summary test rescue team", team_type="Rescue")
        other = User(full_name="Other citizen", email="summary-other@example.com",
                     password_hash=synthetic_password_hash, role=Role.CITIZEN)
        db.add_all([team, other])
        db.flush()
        db.get(User, api.users["response_team"]).team_id = team.id
        incident = Incident(report_reference="RESQ LEGACY SUMMARY", user_id=api.users["citizen"],
                            message="A child is trapped upstairs. No one has been injured.",
                            location="Kochi", people_affected=3, help_required="Boat", status="SUBMITTED")
        db.add(incident)
        db.commit()
        api.incident_id, api.team_id = incident.id, team.id
        api.other_citizen_id = other.id
    api.summary_path = f"/api/incidents/{api.incident_id}/summary"
    return api


def test_missing_legacy_summary_is_explicit_and_admin_can_generate(legacy_report):
    api = legacy_report
    missing = api.client.get(api.summary_path, headers=api.headers("citizen"))
    assert missing.status_code == 404
    assert "No generated summary" in missing.json()["detail"]
    generated = api.client.post(api.summary_path, headers=api.headers("admin"))
    assert generated.status_code == 200, generated.text
    result = generated.json()
    assert result["incident_id"] == api.incident_id
    assert result["method"] == "local_extractive_v1" and result["method_label"] == "Local extractive draft"
    assert result["created_by_id"] == api.users["admin"]
    assert result["created_at"].endswith("Z") or result["created_at"].endswith("+00:00")
    assert "No one has been injured." in result["summary"]
    assert api.client.get(api.summary_path, headers=api.headers("citizen")).json() == result


@pytest.mark.parametrize("role,status", [(None, 401), ("citizen", 403), ("response_team", 403)])
def test_only_admins_generate_drafts(legacy_report, role, status):
    api = legacy_report
    response = api.client.post(api.summary_path, headers=api.headers(role) if role else {})
    assert response.status_code == status


def test_summary_read_access_matches_incident_access(legacy_report):
    api = legacy_report
    assert api.client.post(api.summary_path, headers=api.headers("admin")).status_code == 200
    assert api.client.get(api.summary_path).status_code == 401
    assert api.client.get(api.summary_path, headers=api.headers("response_team")).status_code == 403
    with api.sessions() as db:
        incident = db.get(Incident, api.incident_id)
        incident.assigned_team_id = api.team_id
        db.commit()
    assert api.client.get(api.summary_path, headers=api.headers("response_team")).status_code == 200
    with api.sessions() as db:
        db.get(Incident, api.incident_id).user_id = api.other_citizen_id
        db.commit()
    assert api.client.get(api.summary_path, headers=api.headers("citizen")).status_code == 403


def test_refresh_upserts_without_changing_reviewed_analysis_or_report(legacy_report):
    api = legacy_report
    with api.sessions() as db:
        incident = db.get(Incident, api.incident_id)
        original = (incident.message, incident.location, incident.status, incident.updated_at)
        assessment = IncidentAnalysis(incident_id=incident.id, summary="Reviewed manual assessment.",
                                      severity="LOW", alert_match="NO_MATCH", requires_investigation=False,
                                      source="MANUAL_DEMO", reviewed_by_user_id=api.users["admin"])
        db.add(assessment)
        db.commit()
        assessment_id = assessment.id
    first = api.client.post(api.summary_path, headers=api.headers("admin")).json()
    second = api.client.post(api.summary_path, headers=api.headers("admin")).json()
    assert first["id"] == second["id"] and first["summary"] == second["summary"]
    assert first["input_hash"] == second["input_hash"]
    with api.sessions() as db:
        assert len(list(db.scalars(select(IncidentSummary)))) == 1
        incident = db.get(Incident, api.incident_id)
        assert (incident.message, incident.location, incident.status, incident.updated_at) == original
        assessment = db.get(IncidentAnalysis, assessment_id)
        assert (assessment.summary, assessment.severity, assessment.alert_match,
                assessment.requires_investigation, assessment.source) == (
                    "Reviewed manual assessment.", "LOW", "NO_MATCH", False, "MANUAL_DEMO")


def test_save_summary_flushes_inside_callers_transaction_and_rolls_back(legacy_report):
    api = legacy_report
    with api.sessions() as db:
        save_summary(db, db.get(Incident, api.incident_id), api.users["citizen"])
        assert get_saved_count(db) == 1
        db.rollback()
    with api.sessions() as db:
        assert get_saved_count(db) == 0


def get_saved_count(db):
    return len(list(db.scalars(select(IncidentSummary))))


def test_failed_refresh_rolls_back_and_preserves_existing_draft(legacy_report):
    api = legacy_report
    original = api.client.post(api.summary_path, headers=api.headers("admin")).json()

    def fail_summary(_mapper, _connection, _target):
        raise SQLAlchemyError("Synthetic summary storage failure")

    event.listen(IncidentSummary, "before_update", fail_summary)
    try:
        failed = api.client.post(api.summary_path, headers=api.headers("admin"))
        assert failed.status_code == 503
        assert "could not be saved" in failed.json()["detail"]
    finally:
        event.remove(IncidentSummary, "before_update", fail_summary)
    assert api.client.get(api.summary_path, headers=api.headers("citizen")).json() == original


def test_new_submission_saves_summary_in_the_incident_transaction(api):
    response = api.client.post("/api/incidents/", headers=api.headers("citizen"), json={
        "message": "Flood water entered our home. No injuries have been reported.",
        "location": "Kochi", "people_affected": 2,
    })
    assert response.status_code == 201, response.text
    incident_id = response.json()["id"]
    draft = api.client.get(f"/api/incidents/{incident_id}/summary", headers=api.headers("citizen"))
    assert draft.status_code == 200, draft.text
    assert "No injuries have been reported." in draft.json()["summary"]
    assert draft.json()["created_by_id"] == api.users["citizen"]
    with api.sessions() as db:
        assert db.get(Incident, incident_id).status == "SUBMITTED"
        assert len(list(db.scalars(select(IncidentStatusHistory)))) == 1


def test_failed_initial_summary_rolls_back_incident_and_history(api):
    def fail_summary(_mapper, _connection, _target):
        raise SQLAlchemyError("Synthetic initial summary failure")

    event.listen(IncidentSummary, "before_insert", fail_summary)
    try:
        response = api.client.post("/api/incidents/", headers=api.headers("citizen"), json={
            "message": "Water entered the school; please send assistance.", "location": "Kochi",
        })
        assert response.status_code == 503
    finally:
        event.remove(IncidentSummary, "before_insert", fail_summary)
    with api.sessions() as db:
        assert list(db.scalars(select(Incident))) == []
        assert list(db.scalars(select(IncidentStatusHistory))) == []
        assert list(db.scalars(select(IncidentSummary))) == []


@pytest.mark.parametrize("method", ["get", "post"])
def test_missing_incident_is_404(api, method):
    response = getattr(api.client, method)("/api/incidents/999999/summary", headers=api.headers("admin"))
    assert response.status_code == 404
