"""HTMX Week 2 boundaries: tab auth, roles, local time, and saved evidence."""
import importlib
import os

import httpx
import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("ALLOW_SQLITE_FOR_TESTS", "true")
os.environ.setdefault("JWT_SECRET", "week2-ui-tests-synthetic-secret-with-at-least-32-characters")

web = importlib.import_module("web.app")


@pytest.fixture
def workspace(monkeypatch):
    calls = []
    state = {"validation_error": False, "analysis": None, "configured": True,
             "report_analysis": None, "investigation": None, "predicted_severity": "Moderate",
             "assessment_error": False, "severity_error": False}
    place = {"id": "locality:chengannur", "name": "Chengannur", "district": "Alappuzha", "kind": "locality"}
    alert = {"id": 3, "title": "River warning", "message": "Keep clear of the river.", "level": "ORANGE",
             "place_id": place["id"], "starts_at": "2026-10-15T04:30:00Z", "expires_at": "2026-10-16T09:30:00Z",
             "expired_at": None, "status": "ACTIVE"}

    async def api_call(request, method, path, payload=None):
        calls.append((method, path, payload))
        role = request.headers.get("Authorization", "").removeprefix("Bearer ")
        if path == "/api/users/me":
            return httpx.Response(200, json={"id": 1, "role": role, "full_name": "Test User"})
        if method == "GET" and (path.endswith("/clarifications") or path == "/api/operations/tasks"):
            return httpx.Response(200, json=[])
        if method == "GET" and path == "/api/operations/incidents/7/task":
            return httpx.Response(200, content="null")
        if path == "/api/alerts/places":
            return httpx.Response(200, json=[place])
        if method == "GET" and path.startswith("/api/alerts"):
            return httpx.Response(200, json=[alert])
        if path.startswith("/api/alerts"):
            if state["validation_error"]:
                return httpx.Response(422, json={"detail": "The alert expiry must be after its start."})
            return httpx.Response(201 if method == "POST" and path == "/api/alerts" else 200, json=alert)
        if path == "/api/agent/status":
            return httpx.Response(200, json={"configured": state["configured"], "model": "gemma4:e4b-it-q4_K_M",
                                             "provider": "ollama", "reachable": state["configured"],
                                             "model_available": state["configured"], "reason": state.get("agent_reason")})
        if path == "/api/incidents/7/summary":
            return httpx.Response(404, json={"detail": "No generated summary is available."})
        if path == "/api/admin/incidents/7/analysis":
            if method == "PUT":
                if state["assessment_error"]:
                    return httpx.Response(422, json={"detail": "Choose a supported severity."})
                state["report_analysis"] = {"id": 4, "incident_id": 7, "updated_at": "2026-10-15T05:00:00Z", **payload}
            return httpx.Response(200, json=state["report_analysis"]) if state["report_analysis"] else httpx.Response(200, content="null")
        if path == "/api/ai/predict-severity":
            if state["severity_error"]:
                return httpx.Response(503, json={"detail": "The severity model is temporarily unavailable."})
            return httpx.Response(200, json={"predicted_severity": state["predicted_severity"]})
        if path == "/api/ai/incidents/7/predict-severity":
            if state["severity_error"]:
                return httpx.Response(503, json={"detail": "The severity model is temporarily unavailable."})
            severity = {"High": "HIGH", "Moderate": "MEDIUM", "Low": "LOW"}.get(state["predicted_severity"])
            if severity is None:
                return httpx.Response(502, json={"detail": "The severity model returned an unsupported result."})
            previous = state["report_analysis"] or {
                "extracted_location": None, "alert_match": "NOT_CHECKED", "summary": None,
                "requires_investigation": True,
            }
            state["report_analysis"] = {"id": 4, "incident_id": 7, "updated_at": "2026-10-15T05:00:00Z",
                                        **previous, "severity": severity, "source": "AI_MODULE"}
            return httpx.Response(200, json=state["report_analysis"])
        if path == "/api/admin/incidents/7/investigation":
            if method == "POST":
                state["investigation"] = {"id": 8, "incident_id": 7, "status": "IN_PROGRESS", "findings": None,
                                          "action_taken": None, "updated_at": "2026-10-15T05:00:00Z", **payload}
            return httpx.Response(201 if method == "POST" else 200, json=state["investigation"]) if state["investigation"] else httpx.Response(200, content="null")
        if path == "/api/admin/incidents/investigations/8":
            state["investigation"].update(payload)
            return httpx.Response(200, json=state["investigation"])
        if path.endswith("/location-analysis"):
            if state["analysis"]:
                return httpx.Response(200, json=state["analysis"])
            return httpx.Response(404, json={"detail": "No saved analysis"})
        if path.endswith("/history") or path == "/api/teams":
            return httpx.Response(200, json=[])
        if path == "/api/incidents/7":
            return httpx.Response(200, json={"id": 7, "message": "Water near Chengannur bridge.", "location": "Chengannur",
                                             "status": "SUBMITTED", "created_at": "2026-10-15T04:30:00Z"})
        raise AssertionError((method, path))

    monkeypatch.setattr(web, "api_call", api_call)
    client = TestClient(web.app)
    client.headers.update({"X-ResQ-Page": "true", "Authorization": "Bearer admin"})
    client.get("/alerts")
    yield client, calls, state
    client.close()


def submit(client, path, **values):
    return client.post(path, data={"_csrf": client.cookies.get(web.CSRF_COOKIE), **values}, headers={"HX-Request": "true"})


def test_alert_navigation_bootstrap_and_role_boundary(workspace):
    client, calls, _ = workspace
    full = client.get("/alerts")
    assert 'data-nav="alerts"' in full.text
    assert 'id="alert-form"' in full.text
    client.headers.pop("X-ResQ-Page")
    assert "Opening your workspace" in client.get("/alerts").text
    client.headers["X-ResQ-Page"] = "true"
    client.headers["Authorization"] = "Bearer citizen"
    page = client.get("/alerts", headers={"HX-Request": "true"})
    assert "<html" not in page.text.lower()
    assert "Active alerts" in page.text
    assert 'id="alert-form"' not in page.text
    assert not any(method == "POST" for method, _, _ in calls)
    assert submit(client, "/ui/alerts", title="Unauthorised").status_code == 403
    assert not any(method == "POST" for method, _, _ in calls)
    assert client.post("/ui/alerts", data={"title": "No CSRF"}).status_code == 403


def test_alert_form_ist_conversion_edit_values_and_validation(workspace):
    client, calls, state = workspace
    editing = client.get("/alerts?edit=3")
    assert 'value="2026-10-15T10:00"' in editing.text
    assert 'value="2026-10-16T15:00"' in editing.text
    values = {"title": "River warning", "message": "Stay away from water.", "level": "RED",
              "place_id": "locality:chengannur", "starts_at": "2026-10-15T10:00", "expires_at": "2026-10-16T15:00"}
    response = submit(client, "/ui/alerts", **values)
    assert response.headers["HX-Redirect"] == "/alerts?notice=created"
    payload = next(payload for method, path, payload in calls if method == "POST" and path == "/api/alerts")
    assert payload["starts_at"] == "2026-10-15T10:00:00+05:30"
    assert payload["expires_at"] == "2026-10-16T15:00:00+05:30"
    calls.clear()
    assert submit(client, "/ui/alerts", **{**values, "starts_at": ""}).status_code == 200
    assert "starts_at" not in next(payload for method, path, payload in calls if method == "POST")
    state["validation_error"] = True
    invalid = submit(client, "/ui/alerts/3/update", **{**values, "title": '<script>alert("x")</script>'})
    assert invalid.status_code == 422
    assert "The alert expiry must be after its start." in invalid.text
    assert '<script>alert("x")</script>' not in invalid.text
    assert "&lt;script&gt;" in invalid.text
    assert 'value="2026-10-16T15:00"' in invalid.text
    invalid_time = submit(client, "/ui/alerts", **{**values, "expires_at": "bad-time"})
    assert invalid_time.status_code == 422
    assert "enter a valid date and time in IST" in invalid_time.text
    state["validation_error"] = False
    assert submit(client, "/ui/alerts/3/expire").headers["HX-Redirect"] == "/alerts?notice=expired"


@pytest.mark.parametrize("model, label", [("gemma4:e4b-it-q4_K_M", "Gemma 4 via Ollama"),
                                         ("gemini-3.1-flash-live-preview", "Gemini agent")])
def test_admin_location_card_modes_freshness_and_tool_evidence(workspace, model, label):
    client, calls, state = workspace
    state["configured"] = False
    detail = client.get("/reports/7")
    assert 'id="location-analysis"' in detail.text
    assert 'value="agent" class="button button-primary" disabled' in detail.text
    assert "Location lookup is available now" in detail.text
    assert "Run Gemma 4 agent" in detail.text
    assert "API key" not in detail.text
    state["configured"] = True
    state["analysis"] = {
        "id": 2, "incident_id": 7, "mode": "agent", "model": model, "created_at": "2026-10-15T05:00:00Z",
        "extraction": {"status": "UNCERTAIN", "place": None, "reason": "Two places need review.",
                       "candidates": [{"name": "Chengannur", "district": "Alappuzha"}]},
        "alert_match": {"status": "UNCERTAIN", "reason": "Confirm the location.", "alerts": [], "checked_at": "2026-10-15T05:00:00Z"},
        "tool_calls": [{"name": "lookup_places", "arguments": {"query": "<bridge>"}, "output": {"status": "UNCERTAIN"}}],
        "warning": None,
    }
    result = submit(client, "/ui/reports/7/location-analysis", mode="agent")
    assert result.status_code == 200
    assert "<html" not in result.text.lower()
    assert label in result.text
    assert "Needs review" in result.text
    assert "Possible locations" in result.text
    assert "Agent actions (1)" in result.text
    assert "Lookup Places" in result.text
    assert "Run it again for current matches" in result.text
    assert ("POST", "/api/incidents/7/location-analysis", {"use_agent": True}) in calls
    client.headers["Authorization"] = "Bearer citizen"
    assert 'id="location-analysis"' not in client.get("/reports/7").text
    assert submit(client, "/ui/reports/7/location-analysis", mode="agent").status_code == 403


def test_admin_location_card_explains_ollama_availability_and_escapes_server_reason(workspace):
    client, _, state = workspace
    state["configured"] = False
    state["agent_reason"] = "Start Ollama to load <configured-model>."
    page = client.get("/reports/7")
    assert "Gemma 4 via Ollama is unavailable" in page.text
    assert "Start Ollama to load &lt;configured-model&gt;" in page.text
    assert "<configured-model>" not in page.text
    assert 'value="agent" class="button button-primary" disabled' in page.text


def test_admin_assessment_and_investigation_ui_complete_workflow(workspace):
    client, calls, state = workspace
    page = client.get("/reports/7")
    assert 'id="report-analysis"' in page.text and 'id="investigation"' in page.text
    assert "Predict severity" in page.text
    response = submit(client, "/ui/reports/7/analysis", severity="HIGH", extracted_location="Chengannur",
                      alert_match="MATCH", summary="Location and warning reviewed.", requires_investigation="yes")
    assert response.headers["HX-Redirect"] == "/reports/7"
    assert state["report_analysis"] == {
        "id": 4, "incident_id": 7, "updated_at": "2026-10-15T05:00:00Z", "severity": "HIGH",
        "extracted_location": "Chengannur", "alert_match": "MATCH", "summary": "Location and warning reviewed.",
        "requires_investigation": True, "source": "MANUAL_DEMO",
    }
    assert "Start investigation" in client.get("/reports/7").text
    assert submit(client, "/ui/reports/7/investigation/start", assigned_to_name="Field officer").headers["HX-Redirect"] == "/reports/7"
    assert "Save investigation" in client.get("/reports/7").text
    completed = submit(client, "/ui/reports/7/investigation/update", status="COMPLETED",
                       findings="All residents are safe.", action_taken="Rescue team confirmed safety.")
    assert completed.headers["HX-Redirect"] == "/reports/7"
    assert ("PATCH", "/api/admin/incidents/investigations/8", {
        "status": "COMPLETED", "findings": "All residents are safe.", "action_taken": "Rescue team confirmed safety.",
    }) in calls
    finished = client.get("/reports/7")
    assert "All residents are safe." in finished.text and "Rescue team confirmed safety." in finished.text
    assert "This investigation is complete" in finished.text
    assert "Save investigation" not in finished.text and "Start investigation" not in finished.text


def test_severity_prediction_preserves_assessment_and_normalizes_model_labels(workspace):
    client, calls, state = workspace
    state["report_analysis"] = {
        "severity": "HIGH", "extracted_location": "Chengannur", "alert_match": "UNCERTAIN",
        "summary": "A reviewer must confirm the street.", "requires_investigation": False, "source": "MANUAL_DEMO",
    }
    result = submit(client, "/ui/reports/7/severity")
    assert result.status_code == 200
    assert "Severity prediction saved" in result.text
    assert ("POST", "/api/ai/incidents/7/predict-severity", None) in calls
    assert state["report_analysis"]["severity"] == "MEDIUM"
    assert state["report_analysis"]["summary"] == "A reviewer must confirm the street."
    assert state["report_analysis"]["extracted_location"] == "Chengannur"
    assert state["report_analysis"]["requires_investigation"] is False
    assert not any(method == "PUT" for method, _, _ in calls)
    state["predicted_severity"] = "unsupported"
    calls.clear()
    failed = submit(client, "/ui/reports/7/severity")
    assert failed.status_code == 502 and "unsupported result" in failed.text
    assert not any(method == "PUT" for method, _, _ in calls)


def test_investigation_ui_reports_missing_start_and_validation_without_losing_input(workspace):
    client, calls, state = workspace
    missing = submit(client, "/ui/reports/7/investigation/update", status="COMPLETED", findings="Checked safely.")
    assert missing.status_code == 409 and "Start an investigation before updating it" in missing.text
    assert not any(method == "PATCH" for method, _, _ in calls)
    state["assessment_error"] = True
    invalid = submit(client, "/ui/reports/7/analysis", analysis_form="yes", severity="HIGH",
                     extracted_location='<script>alert("x")</script>', summary="Please preserve this note.",
                     requires_investigation="no")
    assert invalid.status_code == 422 and "Choose a supported severity" in invalid.text
    assert "Please preserve this note." in invalid.text
    assert '<script>alert("x")</script>' not in invalid.text and "&lt;script&gt;" in invalid.text
    assert 'value="no" selected' in invalid.text
    state["severity_error"] = True
    calls.clear()
    failed = submit(client, "/ui/reports/7/severity")
    assert failed.status_code == 503 and "severity model is temporarily unavailable" in failed.text
    assert not any(method == "PUT" for method, _, _ in calls)


@pytest.mark.parametrize("role", ["citizen", "response_team"])
def test_investigation_and_severity_ui_enforce_admin_role_and_csrf(workspace, role):
    client, calls, _ = workspace
    client.headers["Authorization"] = f"Bearer {role}"
    page = client.get("/reports/7")
    assert 'id="report-analysis"' not in page.text and 'id="investigation"' not in page.text
    calls.clear()
    for action in ("analysis", "severity", "investigation/start", "investigation/update"):
        assert submit(client, f"/ui/reports/7/{action}").status_code == 403
    assert not any(method in {"PUT", "POST", "PATCH"} for method, _, _ in calls)
    client.headers["Authorization"] = "Bearer admin"
    assert client.post("/ui/reports/7/severity", data={}).status_code == 403
