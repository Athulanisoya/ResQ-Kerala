"""Revision-bound review decisions preserve citizen reports and evidence provenance."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from tests.test_web import clients, login, post
from backend.routers import week4_workflow


@pytest.fixture
def review_case(clients, monkeypatch):
    citizen, admin, team = clients
    login(citizen, "citizen")
    original = "<script>untrusted()</script> Water entered our house; 2 people need rescue."
    created = post(citizen, "/ui/reports", message=original, location="Kochi",
                   people_affected="2", help_required="Rescue")
    incident_id = int(created.headers["HX-Redirect"].rsplit("/", 1)[1])
    login(admin, "admin")
    login(team, "response_team")

    async def analysis(db, incident, **kwargs):
        return {"status": "complete", "incident_id": incident.id, "original_text": incident.message,
                "model": "synthetic-local-test", "translation": "2 people need rescue.",
                "generative_summary": "2 people reported flood water in Kochi.", "results": {
                    "tool_1_extract_location": {"status": "RESOLVED", "place": {"name": "Kochi", "district": "Ernakulam"},
                                                "reason": "Matched reported place", "matched_text": ["Kochi"]},
                    "tool_2_check_alerts": {"status": "NO_MATCH", "reason": "No attached active alert", "alerts": []},
                    "tool_3_predict_severity": {"predicted_severity": "High"},
                    "tool_4_create_summary": {"summary": "Local extractive summary"},
                    "tool_5_retrieve_safety_evidence": {"passages": [
                        {"title": "Untrusted reference title", "text": "<script>source()</script> Project safety passage.",
                         "source_url": "javascript:alert(1)", "source_name": "Project reference", "chunk_number": 1,
                         "approval_status": "unverified", "review_required": True},
                        {"title": "Supporting page", "text": "Synthetic supporting passage", "source_url": "https://example.org/safety",
                         "source_name": "Synthetic reference", "chunk_number": 2, "approval_status": "unverified", "review_required": True}]},
                    "tool_6_search_shelters": {"shelters": []},
                }}

    monkeypatch.setattr(week4_workflow, "run_week4_workflow", analysis)
    path = f"/api/incidents/{incident_id}"
    run = admin.post(path + "/week4-analysis?use_ai=false")
    assert run.status_code == 200, run.text
    return SimpleNamespace(citizen=citizen, admin=admin, team=team, id=incident_id, path=path, original=original)


def decide(case, key, decision="accepted", **values):
    return case.admin.post(case.path + "/week4-analysis/1/reviews", json={
        "suggestion_key": key, "decision": decision, **values})


def test_review_context_is_admin_only_and_reporter_details_are_allowlisted(review_case):
    case = review_case
    response = case.admin.get(case.path + "/review-context")
    assert response.status_code == 200
    data = response.json()
    assert data["report"]["message"] == case.original
    assert data["reporter"]["email"] == "citizen@example.com"
    assert set(data["reporter"]) == {"id", "full_name", "email", "role", "active", "team_id", "created_at"}
    assert "password" not in response.text and "token" not in response.text
    for client in (case.citizen, case.team):
        denied = client.get(case.path + "/review-context")
        assert denied.status_code == 403
        assert "citizen@example.com" not in denied.text
        assert client.post(case.path + "/week4-analysis/1/reviews", json={
            "suggestion_key": "summary", "decision": "accepted"}).status_code == 403


def test_accept_edit_reject_are_audited_without_overwriting_original_or_assessment(review_case):
    case = review_case
    saved = case.admin.put(f"/api/admin/incidents/{case.id}/analysis", json={
        "severity": "LOW", "extracted_location": "Reviewed original locality", "alert_match": "UNCERTAIN",
        "summary": "Reviewed original assessment", "requires_investigation": False, "source": "MANUAL_DEMO"})
    assert saved.status_code == 200, saved.text
    before = saved.json()
    accepted = decide(case, "summary")
    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["reviewed_value"] == "2 people reported flood water in Kochi."
    edited = decide(case, "summary", "edited", value="Reviewed summary with follow-up required", expected_review_id=accepted.json()["id"])
    assert edited.status_code == 201
    rejected = decide(case, "summary", "rejected", note="The detail has not been confirmed", expected_review_id=edited.json()["id"])
    assert rejected.status_code == 201
    assert rejected.json()["reviewed_value"] is None
    context = case.admin.get(case.path + "/review-context").json()
    summary = next(s for s in context["suggestions"] if s["key"] == "summary")
    assert [r["decision"] for r in summary["review_history"]] == ["rejected", "edited", "accepted"]
    assert summary["review_history"][2]["reviewed_value"] == accepted.json()["reviewed_value"]
    assert all(r["reviewed_by"] and r["created_at"] for r in summary["review_history"])
    assert context["report"]["message"] == case.original
    assert context["report"]["people_affected"] == 2
    assert case.admin.get(f"/api/admin/incidents/{case.id}/analysis").json() == before


def test_duplicate_and_stale_decisions_cannot_overwrite_a_later_review(review_case):
    case = review_case
    first = decide(case, "people_affected", "edited", value="3")
    assert first.status_code == 201
    retry = decide(case, "people_affected", "edited", value="4")
    assert retry.status_code == 409
    assert case.admin.post(case.path + "/week4-analysis?use_ai=false").status_code == 200
    stale = decide(case, "people_affected", "rejected", note="Stale", expected_review_id=first.json()["id"])
    assert stale.status_code == 409
    context = case.admin.get(case.path + "/review-context").json()
    assert context["revisions"][0]["revision"] == 2
    assert context["revisions"][0]["reviews"] == []
    assert context["revisions"][1]["reviews"][0]["reviewed_value"] == 3


@pytest.mark.parametrize("key,decision,value,note", [
    ("missing_field", "accepted", None, None),
    ("summary", "rejected", None, None),
    ("summary", "edited", " ", None),
    ("people_affected", "edited", "3.5", None),
    ("people_affected", "edited", "-1", None),
    ("severity", "edited", "Severe", None),
    ("alert_match", "edited", "SAFE", None),
])
def test_invalid_or_unavailable_suggestions_cannot_be_reviewed(review_case, key, decision, value, note):
    assert decide(review_case, key, decision, value=value, note=note).status_code == 422


def test_review_panel_has_evidence_links_safe_sources_and_no_raw_tool_json(review_case):
    case = review_case
    page = case.admin.get(f"/ui/reports/{case.id}/week4-analysis", headers={"HX-Request": "true"})
    assert page.status_code == 200, page.text
    assert 'href="#review-original-message"' in page.text
    assert 'href="#review-location-evidence"' in page.text
    assert 'href="#review-alert-evidence"' in page.text
    assert 'href="https://example.org/safety"' in page.text
    assert "javascript:alert" not in page.text
    assert "<script>source()" not in page.text and "&lt;script&gt;source()" in page.text
    assert "<script>untrusted()" not in page.text and "&lt;script&gt;untrusted()" in page.text
    assert "Reporter account details" in page.text and "citizen@example.com" in page.text
    assert 'name="decision" value="accepted"' in page.text
    assert 'name="decision" value="edited"' in page.text
    assert 'name="decision" value="rejected"' in page.text
    assert "<pre>" not in page.text and "tool_1_extract_location" not in page.text


def test_review_form_keeps_invalid_edit_and_note_and_requires_csrf(review_case):
    case = review_case
    url = f"/ui/reports/{case.id}/week4-analysis/1/review"
    response = post(case.admin, url, suggestion_key="people_affected", decision="edited",
                    value="not a number", note="Retain this note", expected_review_id="0")
    assert response.status_code == 422, response.text
    assert "not a number</textarea>" in response.text
    assert "Retain this note</textarea>" in response.text
    assert "whole number" in response.text
    denied = case.admin.post(url, data={"suggestion_key": "summary", "decision": "accepted", "_csrf": "invalid"})
    assert denied.status_code == 403
    saved = post(case.admin, url, suggestion_key="people_affected", decision="edited", value="4", expected_review_id="0")
    assert saved.status_code == 200
    assert "Review decision saved" in saved.text


def test_revision_numbers_cannot_be_reused_to_review_another_incident(review_case):
    case = review_case
    other = post(case.citizen, "/ui/reports", message="Another synthetic report needs assistance.",
                 location="Alappuzha", people_affected="1")
    other_id = int(other.headers["HX-Redirect"].rsplit("/", 1)[1])
    response = case.admin.post(f"/api/incidents/{other_id}/week4-analysis/1/reviews", json={
        "suggestion_key": "summary", "decision": "accepted"})
    assert response.status_code == 404


def test_accepting_a_suggestion_ignores_the_unused_editor_value(review_case):
    case = review_case
    response = post(case.admin, f"/ui/reports/{case.id}/week4-analysis/1/review",
                    suggestion_key="summary", decision="accepted", value="x" * 6000, expected_review_id="0")
    assert response.status_code == 200
    reviews = case.admin.get(case.path + "/review-context").json()["revisions"][0]["reviews"]
    assert reviews[0]["decision"] == "accepted"
    assert reviews[0]["reviewed_value"] == reviews[0]["original_value"]


def test_unavailable_tool_outputs_do_not_become_acceptable_suggestions(review_case, monkeypatch):
    case = review_case
    result = deepcopy(case.admin.get(case.path + "/week4-analysis").json()[0]["result"])
    result["results"]["tool_1_extract_location"]["status"] = "UNCERTAIN"
    result["results"]["tool_2_check_alerts"] = {"status": "not_run", "reason": "Location unavailable"}

    async def unavailable(*args, **kwargs):
        return result

    monkeypatch.setattr(week4_workflow, "run_week4_workflow", unavailable)
    assert case.admin.post(case.path + "/week4-analysis?use_ai=false").status_code == 200
    keys = {s["key"] for s in case.admin.get(case.path + "/review-context").json()["suggestions"]}
    assert "location" not in keys and "alert_match" not in keys
    assert case.admin.post(case.path + "/week4-analysis/2/reviews", json={
        "suggestion_key": "alert_match", "decision": "accepted"}).status_code == 422
