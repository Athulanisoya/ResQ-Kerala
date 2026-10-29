"""Exercise the actual HTML → API → database case flow across Athul's weeks."""
from test_web import clients, login, post
from importlib import import_module
import httpx


def create_case(citizen):
    login(citizen, "citizen")
    response = post(citizen, "/ui/reports", message="Water entered our house; four people need evacuation.",
                    location="Chengannur", people_affected="4", help_required="Rescue")
    return int(response.headers["HX-Redirect"].rsplit("/", 1)[-1])


def test_citizen_clarification_to_final_admin_closure(clients):
    citizen, admin, team = clients
    incident_id = create_case(citizen)
    path = f"/reports/{incident_id}"
    login(admin, "admin")
    requested = post(admin, f"/ui/reports/{incident_id}/clarifications", question="Is the road passable?", required="yes")
    assert requested.headers["HX-Redirect"] == path
    clarification = citizen.get(f"/api/communication/incidents/{incident_id}/clarifications").json()[0]
    citizen_page = citizen.get(path)
    assert "Is the road passable?" in citizen_page.text and "Send reply" in citizen_page.text
    assert "Request clarification" not in citizen_page.text
    reply = post(citizen, f"/ui/reports/{incident_id}/clarifications/{clarification['id']}/reply",
                 reply_message="Only the east road is passable.")
    assert reply.headers["HX-Redirect"] == path
    assert citizen.get(f"/api/incidents/{incident_id}").json()["message"].startswith("Water entered our house")
    assert "Only the east road is passable." in citizen.get(path).text
    assert "clarification replied" in citizen.get(path).text.lower()
    post(admin, f"/ui/reports/{incident_id}/review", status="VERIFIED")
    post(admin, f"/ui/reports/{incident_id}/assign", team_id="1")
    login(team, "response_team")
    accepted = post(team, f"/ui/operations/incidents/{incident_id}/accept")
    assert accepted.headers.get("HX-Redirect") == path, accepted.text
    for status in ("EN_ROUTE", "IN_PROGRESS", "RESOLVED"):
        response = post(team, f"/ui/operations/incidents/{incident_id}/progress", status=status, note="Synthetic workflow check")
        assert response.headers.get("HX-Redirect") == path, response.text
    assert "Ready for final review" in citizen.get(path).text
    assert post(citizen, f"/ui/reports/{incident_id}/close").status_code == 403
    assert post(admin, f"/ui/reports/{incident_id}/close", closure_note="Evacuation and welfare check complete.").headers["HX-Redirect"] == path
    closed = citizen.get(path)
    assert "Case closed" in closed.text and "Evacuation and welfare check complete." in closed.text
    assert "Send reply" not in closed.text
    assert "Chengannur" in citizen.get("/reports?status=CLOSED&q=chengannur").text
    assert "No matching reports" in citizen.get("/reports?status=SUBMITTED&q=chengannur").text
    assert "1</strong> closed cases" in citizen.get("/dashboard").text


def test_private_updates_read_controls_and_bootstrap(clients):
    citizen, admin, _ = clients
    incident_id = create_case(citizen)
    updates = citizen.get("/updates")
    assert "Report submitted" in updates.text and f'/reports/{incident_id}' in updates.text
    assert 'hx-trigger="load, every 30s' in updates.text
    # Polls must override the enclosing link's target and history settings.
    assert 'id="updates-count" hx-target="this" hx-push-url="false"' in updates.text
    notifications = citizen.get("/api/communication/notifications").json()
    assert notifications["unread_count"] >= 1
    record = notifications["notifications"][0]
    assert post(citizen, f"/ui/updates/{record['id']}/read").headers["HX-Redirect"] == "/updates"
    assert post(citizen, "/ui/updates/read-all").status_code == 200
    assert "No unread updates" in citizen.get("/ui/updates/count").text
    citizen.headers.pop("X-ResQ-Page")
    assert "Opening your workspace" in citizen.get("/updates").text
    citizen.headers["X-ResQ-Page"] = "true"
    assert citizen.post("/ui/updates/read-all", data={}).status_code == 403
    login(admin, "admin")
    assert "Report submitted" in admin.get("/updates").text


def test_clarification_validation_retains_text_and_blocks_early_close(clients):
    citizen, admin, _ = clients
    incident_id = create_case(citizen)
    login(admin, "admin")
    invalid = post(admin, f"/ui/reports/{incident_id}/clarifications", question="x" * 2001, required="yes")
    assert invalid.status_code == 422
    assert "x" * 2001 in invalid.text
    assert post(admin, f"/ui/reports/{incident_id}/close").status_code == 409
    assert "Only a resolved incident can be closed" in post(admin, f"/ui/reports/{incident_id}/close").text


def test_badge_outage_stays_small_and_keeps_session(clients, monkeypatch):
    citizen, _, _ = clients
    login(citizen, "citizen")
    web = import_module("web.app")
    original = web.api_call

    async def unavailable(request, method, path, payload=None):
        if path == "/api/users/me":
            return httpx.Response(503, json={"detail": "Temporary outage"})
        return await original(request, method, path, payload)

    monkeypatch.setattr(web, "api_call", unavailable)
    response = citizen.get("/ui/updates/count", headers={"HX-Request": "true"})
    assert response.status_code == 200 and len(response.text) < 300
    assert "count unavailable" in response.text
    assert "Reconnect" not in response.text and "X-ResQ-Session" not in response.headers


def test_failed_reply_preserves_only_its_form_and_optional_question_choice(clients):
    citizen, admin, _ = clients
    incident_id = create_case(citizen)
    login(admin, "admin")
    for question in ("Which road is open?", "Is there a boat landing?"):
        post(admin, f"/ui/reports/{incident_id}/clarifications", question=question)
    questions = citizen.get(f"/api/communication/incidents/{incident_id}/clarifications").json()
    failed = post(citizen, f"/ui/reports/{incident_id}/clarifications/{questions[0]['id']}/reply",
                  reply_message="z" * 3001)
    assert failed.status_code == 422
    assert failed.text.count("z" * 3001) == 1
    invalid = post(admin, f"/ui/reports/{incident_id}/clarifications", question="x")
    assert invalid.status_code == 422
    checkbox = invalid.text.split('name="required"', 1)[1].split(">", 1)[0]
    assert "checked" not in checkbox


def test_pre_upgrade_clarification_is_visible_and_owner_can_reply(clients):
    from backend.database.connection import get_db
    from backend.main import app as api
    from backend.models import Incident, IncidentStatusHistory
    citizen, admin, team = clients
    incident_id = create_case(citizen)
    path = f"/reports/{incident_id}"
    session_generator = api.dependency_overrides[get_db]()
    db = next(session_generator)
    try:
        db.get(Incident, incident_id).status = "AWAITING_CLARIFICATION"
        db.add(IncidentStatusHistory(incident_id=incident_id, status="AWAITING_CLARIFICATION",
                                     note="Clarification requested by admin 2: Is the road clear?"))
        db.commit()
    finally:
        session_generator.close()
    page = citizen.get(path)
    assert "Earlier clarification request" in page.text and "Is the road clear?" in page.text
    assert f"/ui/reports/{incident_id}/legacy-clarification/reply" in page.text
    login(admin, "admin")
    assert "Send earlier reply" not in admin.get(path).text
    assert post(admin, f"/ui/reports/{incident_id}/legacy-clarification/reply", legacy_reply="Road is clear now.").status_code == 403
    response = post(citizen, f"/ui/reports/{incident_id}/legacy-clarification/reply", legacy_reply="Road is clear now.")
    assert response.status_code == 200 and response.headers["HX-Redirect"] == path
    refreshed = citizen.get(path)
    assert "Send earlier reply" not in refreshed.text
    assert "Road is clear now." in refreshed.text
