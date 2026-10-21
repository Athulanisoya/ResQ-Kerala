"""Generated draft summaries remain separate from reviewed admin assessments."""
from html import escape
from html.parser import HTMLParser
from importlib import import_module

import httpx
import pytest

from test_web import clients, login, post


web = import_module("web.app")


class Textareas(HTMLParser):
    def __init__(self, markup):
        super().__init__()
        self.values = {}
        self.active = None
        self.feed(markup)

    def handle_starttag(self, tag, attrs):
        if tag == "textarea":
            self.active = dict(attrs).get("id")
            if self.active:
                self.values[self.active] = ""

    def handle_data(self, data):
        if self.active:
            self.values[self.active] += data

    def handle_endtag(self, tag):
        if tag == "textarea":
            self.active = None


@pytest.fixture
def summary_report(clients):
    citizen, admin, team = clients
    login(citizen, "citizen")
    login(admin, "admin")
    created = post(citizen, "/ui/reports", message="A child is trapped in a flooded house near the Chengannur bridge. Rescue is needed.",
                   location="Chengannur", people_affected="3", help_required="Rescue")
    assert created.status_code == 200, created.text
    path = created.headers["HX-Redirect"]
    return citizen, admin, team, int(path.rsplit("/", 1)[1]), path


def test_auto_summary_is_visible_to_owner_admin_and_assigned_team(summary_report):
    citizen, admin, team, incident_id, path = summary_report
    summary_path = f"/api/incidents/{incident_id}/summary"
    response = citizen.get(summary_path)
    assert response.status_code == 200, response.text
    draft = response.json()
    assert draft["method"] == "local_extractive_v1" and draft["summary"].strip()
    assert admin.get(summary_path).json() == draft
    for client in (citizen, admin):
        page = client.get(path)
        assert page.status_code == 200
        assert 'id="report-summary"' in page.text
        assert escape(draft["summary"]) in page.text
    assert Textareas(admin.get(path).text).values["analysis-summary"] == draft["summary"]
    assert f'action="/ui/reports/{incident_id}/summary"' not in citizen.get(path).text

    login(team, "response_team")
    assert team.get(summary_path).status_code == 403
    assert post(admin, f"/ui/reports/{incident_id}/review", status="VERIFIED").status_code == 200
    assert post(admin, f"/ui/reports/{incident_id}/assign", team_id="1").status_code == 200
    assert team.get(summary_path).json() == draft
    assigned_page = team.get(path)
    assert assigned_page.status_code == 200 and 'id="report-summary"' in assigned_page.text
    assert escape(draft["summary"]) in assigned_page.text
    assert f'action="/ui/reports/{incident_id}/summary"' not in assigned_page.text


def test_refresh_summary_never_overwrites_manual_assessment_investigation_or_report(summary_report):
    _, admin, _, incident_id, path = summary_report
    reviewed_summary = "Manual review: contact the district coordinator before dispatch."
    saved = post(admin, f"/ui/reports/{incident_id}/analysis", analysis_form="yes", severity="LOW",
                 extracted_location="Chengannur bridge", alert_match="UNCERTAIN", summary=reviewed_summary,
                 requires_investigation="yes")
    assert saved.status_code == 200, saved.text
    assert post(admin, f"/ui/reports/{incident_id}/investigation/start", assigned_to_name="Review officer").status_code == 200
    assert post(admin, f"/ui/reports/{incident_id}/investigation/update", status="IN_PROGRESS",
                findings="Coordinator contacted to confirm the address.", action_taken="Requested a field check.").status_code == 200
    routes = [f"/api/admin/incidents/{incident_id}/analysis", f"/api/admin/incidents/{incident_id}/investigation",
              f"/api/incidents/{incident_id}", f"/api/incidents/{incident_id}/history"]
    before = {route: admin.get(route).json() for route in routes}
    refreshed = post(admin, f"/ui/reports/{incident_id}/summary")
    assert refreshed.status_code == 200, refreshed.text
    assert 'id="report-summary"' in refreshed.text
    for route in routes:
        assert admin.get(route).json() == before[route]
    reloaded = admin.get(path)
    assert Textareas(reloaded.text).values["analysis-summary"] == reviewed_summary
    assert Textareas(refreshed.text).values["analysis-summary"] == reviewed_summary


def test_summary_regeneration_enforces_admin_and_csrf(summary_report):
    citizen, admin, team, incident_id, path = summary_report
    login(team, "response_team")
    action = f"/ui/reports/{incident_id}/summary"
    summary_path = f"/api/incidents/{incident_id}/summary"
    before = admin.get(summary_path).json()
    for client in (citizen, team):
        assert post(client, action).status_code == 403
        assert client.post(summary_path).status_code == 403
    assert admin.post(action, data={}, headers={"HX-Request": "true"}).status_code == 403
    assert admin.post(action, data={"_csrf": "invalid"}, headers={"HX-Request": "true"}).status_code == 403
    assert admin.get(summary_path).json() == before
    assert citizen.get(path).status_code == 200


def test_cleared_reviewed_summary_stays_empty_after_reload_and_draft_refresh(summary_report):
    _, admin, _, incident_id, path = summary_report
    response = post(admin, f"/ui/reports/{incident_id}/analysis", analysis_form="yes",
                    severity="LOW", summary="", requires_investigation="no")
    assert response.status_code == 200
    assert admin.get(f"/api/admin/incidents/{incident_id}/analysis").json()["summary"] is None
    assert Textareas(admin.get(path).text).values["analysis-summary"] == ""
    refreshed = post(admin, f"/ui/reports/{incident_id}/summary")
    assert refreshed.status_code == 200
    assert Textareas(refreshed.text).values["analysis-summary"] == ""


def test_summary_outage_preserves_original_details_and_review_controls(summary_report, monkeypatch):
    _, admin, _, incident_id, path = summary_report
    original_api_call = web.api_call
    summary_path = f"/api/incidents/{incident_id}/summary"

    async def unavailable_summary(request, method, api_path, payload=None):
        if api_path == summary_path:
            return httpx.Response(503, json={"detail": "The summary service is temporarily unavailable."})
        return await original_api_call(request, method, api_path, payload)

    monkeypatch.setattr(web, "api_call", unavailable_summary)
    original_message = admin.get(f"/api/incidents/{incident_id}").json()["message"]
    page = admin.get(path)
    assert page.status_code == 200
    assert original_message in page.text and "Review report" in page.text
    assert "summary service is temporarily unavailable" in page.text
    failure = post(admin, f"/ui/reports/{incident_id}/summary")
    assert failure.status_code == 503
    assert original_message in failure.text and 'id="report-summary"' in failure.text
    assert "summary service is temporarily unavailable" in failure.text


def test_missing_legacy_summary_can_be_generated_without_losing_report_details(summary_report, monkeypatch):
    _, admin, _, incident_id, path = summary_report
    original_api_call = web.api_call
    summary_path = f"/api/incidents/{incident_id}/summary"
    state = {"missing": True}

    async def missing_until_generate(request, method, api_path, payload=None):
        if api_path == summary_path:
            if method == "GET" and state["missing"]:
                return httpx.Response(404, json={"detail": "No generated summary is available."})
            if method == "POST":
                state["missing"] = False
        return await original_api_call(request, method, api_path, payload)

    monkeypatch.setattr(web, "api_call", missing_until_generate)
    page = admin.get(path)
    assert page.status_code == 200 and 'id="report-summary"' in page.text
    assert f'action="/ui/reports/{incident_id}/summary"' in page.text
    regenerated = post(admin, f"/ui/reports/{incident_id}/summary")
    assert regenerated.status_code == 200, regenerated.text
    assert state["missing"] is False
    draft = admin.get(summary_path).json()
    assert escape(draft["summary"]) in regenerated.text


def test_summary_output_is_escaped_in_section_and_assessment_default(summary_report, monkeypatch):
    _, admin, _, incident_id, path = summary_report
    original_api_call = web.api_call
    malicious = '<script>alert("summary")</script> & draft'

    async def escaped_summary(request, method, api_path, payload=None):
        response = await original_api_call(request, method, api_path, payload)
        if api_path == f"/api/incidents/{incident_id}/summary" and response.status_code == 200:
            return httpx.Response(200, json={**response.json(), "summary": malicious})
        return response

    monkeypatch.setattr(web, "api_call", escaped_summary)
    page = admin.get(path)
    assert page.status_code == 200
    assert malicious not in page.text and "&lt;script&gt;" in page.text
    assert Textareas(page.text).values["analysis-summary"] == malicious


def test_predict_severity_retains_unsaved_manual_summary_in_form(summary_report):
    _, admin, _, incident_id, _ = summary_report
    analysis_path = f"/api/admin/incidents/{incident_id}/analysis"
    saved = post(admin, f"/ui/reports/{incident_id}/analysis", analysis_form="yes", severity="LOW",
                 summary="Persisted reviewer note.", extracted_location="Reviewed location", alert_match="UNCERTAIN",
                 requires_investigation="yes")
    assert saved.status_code == 200
    pending = "Unsaved summary still being edited by the reviewer."
    predicted = post(admin, f"/ui/reports/{incident_id}/severity", analysis_form="yes", severity="LOW",
                     summary=pending, extracted_location="Pending location", alert_match="NO_MATCH",
                     requires_investigation="no")
    assert predicted.status_code == 200, predicted.text
    assert Textareas(predicted.text).values["analysis-summary"] == pending
    persisted = admin.get(analysis_path).json()
    assert persisted["severity"] == "HIGH" and persisted["summary"] == "Persisted reviewer note."
    assert persisted["extracted_location"] == "Reviewed location" and persisted["requires_investigation"] is True
