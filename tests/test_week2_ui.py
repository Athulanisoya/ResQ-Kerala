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
    state = {"validation_error": False, "analysis": None, "configured": True}
    place = {"id": "locality:chengannur", "name": "Chengannur", "district": "Alappuzha", "kind": "locality"}
    alert = {"id": 3, "title": "River warning", "message": "Keep clear of the river.", "level": "ORANGE",
             "place_id": place["id"], "starts_at": "2026-10-15T04:30:00Z", "expires_at": "2026-10-16T09:30:00Z",
             "expired_at": None, "status": "ACTIVE"}

    async def api_call(request, method, path, payload=None):
        calls.append((method, path, payload))
        role = request.headers.get("Authorization", "").removeprefix("Bearer ")
        if path == "/api/users/me":
            return httpx.Response(200, json={"id": 1, "role": role, "full_name": "Test User"})
        if path == "/api/alerts/places":
            return httpx.Response(200, json=[place])
        if method == "GET" and path.startswith("/api/alerts"):
            return httpx.Response(200, json=[alert])
        if path.startswith("/api/alerts"):
            if state["validation_error"]:
                return httpx.Response(422, json={"detail": "The alert expiry must be after its start."})
            return httpx.Response(201 if method == "POST" and path == "/api/alerts" else 200, json=alert)
        if path == "/api/agent/status":
            return httpx.Response(200, json={"configured": state["configured"], "model": "gemini-3.1-flash-live-preview"})
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


def test_admin_location_card_modes_freshness_and_tool_evidence(workspace):
    client, calls, state = workspace
    state["configured"] = False
    detail = client.get("/reports/7")
    assert 'id="location-analysis"' in detail.text
    assert 'value="agent" class="button button-primary" disabled' in detail.text
    assert "Location lookup is available now" in detail.text
    state["configured"] = True
    state["analysis"] = {
        "id": 2, "incident_id": 7, "mode": "agent", "model": "gemini-3.1-flash-live-preview", "created_at": "2026-10-15T05:00:00Z",
        "extraction": {"status": "UNCERTAIN", "place": None, "reason": "Two places need review.",
                       "candidates": [{"name": "Chengannur", "district": "Alappuzha"}]},
        "alert_match": {"status": "UNCERTAIN", "reason": "Confirm the location.", "alerts": [], "checked_at": "2026-10-15T05:00:00Z"},
        "tool_calls": [{"name": "lookup_places", "arguments": {"query": "<bridge>"}, "output": {"status": "UNCERTAIN"}}],
        "warning": None,
    }
    result = submit(client, "/ui/reports/7/location-analysis", mode="agent")
    assert result.status_code == 200
    assert "<html" not in result.text.lower()
    assert "Gemini agent" in result.text
    assert "Needs review" in result.text
    assert "Possible locations" in result.text
    assert "Agent actions (1)" in result.text
    assert "Lookup Places" in result.text
    assert "Run it again for current matches" in result.text
    assert ("POST", "/api/incidents/7/location-analysis", {"use_agent": True}) in calls
    client.headers["Authorization"] = "Bearer citizen"
    assert 'id="location-analysis"' not in client.get("/reports/7").text
    assert submit(client, "/ui/reports/7/location-analysis", mode="agent").status_code == 403
