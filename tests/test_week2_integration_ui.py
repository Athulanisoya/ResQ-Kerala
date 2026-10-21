"""Exercise the merged severity, geography and investigation HTML workflow."""
from datetime import datetime, timedelta, timezone

import pytest

from test_web import clients, login, post


@pytest.fixture
def week2_report(clients):
    citizen, admin, team = clients
    login(citizen, "citizen")
    login(admin, "admin")
    message = "A child is trapped inside a flooded house."
    created = post(citizen, "/ui/reports", message=message, location="Chengannur",
                   people_affected="3", help_required="Rescue")
    assert created.status_code == 200, created.text
    path = created.headers["HX-Redirect"]
    return citizen, admin, team, int(path.rsplit("/", 1)[1]), path, message


def test_merged_severity_assessment_and_investigation_through_html(week2_report):
    citizen, admin, _, incident_id, path, message = week2_report
    analysis_path = f"/api/admin/incidents/{incident_id}/analysis"
    investigation_path = f"/api/admin/incidents/{incident_id}/investigation"
    original_report = admin.get(f"/api/incidents/{incident_id}").json()
    original_geography = admin.get(f"/api/incidents/{incident_id}/location-analysis").json()
    detail = admin.get(path)
    assert detail.status_code == 200
    for marker in ('id="location-analysis"', 'id="report-analysis"', 'id="investigation"'):
        assert marker in detail.text

    predicted = post(admin, f"/ui/reports/{incident_id}/severity")
    assert predicted.status_code == 200, predicted.text
    assert "Severity prediction saved" in predicted.text
    assessment = admin.get(analysis_path).json()
    assert assessment["severity"] == "HIGH"
    assert assessment["source"] == "AI_MODULE"
    assert assessment["requires_investigation"] is True

    manual = post(admin, f"/ui/reports/{incident_id}/analysis", analysis_form="yes",
                  severity="LOW", extracted_location="Chengannur bridge",
                  alert_match="UNCERTAIN", summary="Investigate the exact address.",
                  requires_investigation="yes")
    assert manual.status_code == 200, manual.text
    assert manual.headers["HX-Redirect"] == path
    reviewed = admin.get(analysis_path).json()
    assert reviewed["severity"] == "LOW" and reviewed["source"] == "MANUAL_DEMO"
    assert reviewed["extracted_location"] == "Chengannur bridge"

    assert post(admin, f"/ui/reports/{incident_id}/severity").status_code == 200
    updated = admin.get(analysis_path).json()
    assert updated["severity"] == "HIGH"
    for field in ("id", "extracted_location", "alert_match", "summary", "requires_investigation"):
        assert updated[field] == reviewed[field]

    started = post(admin, f"/ui/reports/{incident_id}/investigation/start", assigned_to_name="District reviewer")
    assert started.status_code == 200, started.text
    assert started.headers["HX-Redirect"] == path
    investigation = admin.get(investigation_path).json()
    assert investigation["assigned_to_name"] == "District reviewer"
    assert investigation["status"] == "IN_PROGRESS"
    progress = post(admin, f"/ui/reports/{incident_id}/investigation/update", status="IN_PROGRESS",
                    findings="The bridge location has been confirmed.", action_taken="Contacted the response coordinator.")
    assert progress.status_code == 200, progress.text
    assert progress.headers["HX-Redirect"] == path
    before_reassignment = admin.get(investigation_path).json()
    active_page = admin.get(path)
    assert "Reassign investigator" in active_page.text
    reassigned = post(admin, f"/ui/reports/{incident_id}/investigation/start", assigned_to_name="Field supervisor")
    assert reassigned.status_code == 200 and reassigned.headers["HX-Redirect"] == path
    after_reassignment = admin.get(investigation_path).json()
    assert after_reassignment["assigned_to_name"] == "Field supervisor"
    for field in ("id", "created_by_user_id", "created_at", "status", "findings", "action_taken"):
        assert after_reassignment[field] == before_reassignment[field]
    complete = post(admin, f"/ui/reports/{incident_id}/investigation/update", status="COMPLETED",
                    findings="The child was located and the incident details were verified.",
                    action_taken="Passed findings to the rescue coordinator.")
    assert complete.status_code == 200, complete.text
    completed = admin.get(investigation_path).json()
    assert completed["status"] == "COMPLETED"
    completed_page = admin.get(path)
    assert completed["findings"] in completed_page.text
    assert f'action="/ui/reports/{incident_id}/investigation/update"' not in completed_page.text
    assert "Reassign investigator" not in completed_page.text
    assert post(admin, f"/ui/reports/{incident_id}/investigation/start",
                assigned_to_name="Forbidden reassignment").status_code == 409

    rejected = post(admin, f"/ui/reports/{incident_id}/investigation/update", status="IN_PROGRESS",
                    findings="Attempt to replace the completed investigation.")
    assert rejected.status_code == 409
    assert admin.get(investigation_path).json() == completed
    assert admin.get(f"/api/incidents/{incident_id}").json() == original_report
    assert admin.get(f"/api/incidents/{incident_id}/location-analysis").json() == original_geography
    assert original_report["message"] == message
    assert 'id="report-analysis"' not in citizen.get(path).text


def test_merged_ui_actions_keep_role_and_csrf_boundaries(week2_report):
    citizen, admin, team, incident_id, path, _ = week2_report
    login(team, "response_team")
    actions = (
        ("analysis", {"severity": "HIGH", "requires_investigation": "yes"}),
        ("severity", {}),
        ("investigation/start", {"assigned_to_name": "Unauthorized reviewer"}),
        ("investigation/update", {"status": "COMPLETED", "findings": "Unauthorized findings."}),
    )
    for suffix, payload in actions:
        action = f"/ui/reports/{incident_id}/{suffix}"
        for client in (citizen, team):
            assert post(client, action, **payload).status_code == 403
        assert admin.post(action, data=payload, headers={"HX-Request": "true"}).status_code == 403
    assert admin.get(f"/api/admin/incidents/{incident_id}/analysis").json() is None
    assert admin.get(f"/api/admin/incidents/{incident_id}/investigation").json() is None
    assert citizen.get(path).status_code == 200


def test_existing_alert_account_and_location_routes_survive_integration(week2_report):
    citizen, admin, _, incident_id, _, _ = week2_report
    for client in (citizen, admin):
        assert client.get("/account").status_code == 200
        permissions = client.get("/permissions")
        assert permissions.status_code == 200
        assert "Workspace permissions" in permissions.text
        assert client.get("/alerts").status_code == 200
    expires = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    created = post(admin, "/ui/alerts", title="Synthetic integration alert",
                   message="Synthetic test alert for the district.", level="ORANGE",
                   place_id="alappuzha", expires_at=expires)
    assert created.status_code == 200, created.text
    assert created.headers["HX-Redirect"] == "/alerts?notice=created"
    assert "Synthetic integration alert" in citizen.get("/alerts").text
    checked = post(admin, f"/ui/reports/{incident_id}/location-analysis", mode="lookup")
    assert checked.status_code == 200, checked.text
    assert "Matching active alerts" in checked.text
    assert "Synthetic integration alert" in checked.text
    assert admin.get(f"/api/admin/incidents/{incident_id}/analysis").json() is None
    assert admin.get(f"/api/admin/incidents/{incident_id}/investigation").json() is None
