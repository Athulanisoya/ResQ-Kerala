"""Coverage edits keep CSRF, admin access and deliberate assignment controls."""
from test_web import clients, login, post


def test_coverage_page_and_checkbox_form_save_with_csrf(clients):
    _, admin, _ = clients
    login(admin, "admin")
    teams = admin.get("/api/management/teams").json()
    target = teams[0]["id"]
    page = admin.get(f"/team-coverage/{target}")
    assert page.status_code == 200
    assert "Team operating areas" in page.text
    assert f'name="area:ernakulam"' in page.text
    assert admin.post(f"/ui/teams/{target}/coverage", data={"expected_version": "0"}).status_code == 403
    saved = post(admin, f"/ui/teams/{target}/coverage", expected_version="0", **{
        "area:ernakulam": "true", "area:ernakulam-aluva": "true", "capability:evacuation": "true", "note": "Synthetic operating area"})
    assert saved.status_code == 200, saved.text
    assert "Team operating areas and capabilities saved." in saved.text
    profile = admin.get(f"/api/admin/teams/{target}/coverage").json()
    assert profile["area_ids"] == ["ernakulam", "ernakulam-aluva"]
    assert profile["capabilities"] == ["evacuation"]
    conflict = post(admin, f"/ui/teams/{target}/coverage", expected_version="0", **{"area:thrissur": "true"})
    assert conflict.status_code == 409
    assert 'name="area:thrissur" value="true" checked' in conflict.text


def test_recommendation_partial_only_offers_explicit_assignment_for_verified_report(clients):
    citizen, admin, _ = clients
    login(citizen, "citizen"); login(admin, "admin")
    report = citizen.post("/api/incidents/", json={"message": "Synthetic flood in Aluva", "location": "Aluva, Ernakulam"}).json()
    path = f"/ui/reports/{report['id']}/team-recommendations"
    preview = admin.get(path)
    assert preview.status_code == 200
    assert "Recommendations are a preview" in preview.text
    assert f'action="/ui/reports/{report["id"]}/assign"' not in preview.text
    assert admin.patch(f"/api/incidents/{report['id']}/status", json={"status": "VERIFIED"}).status_code == 200
    checked = admin.get(path)
    assert checked.status_code == 200
    assert f'action="/ui/reports/{report["id"]}/assign"' in checked.text
    assert "Availability is checked again" in checked.text
    assert citizen.get(path).status_code == 403
    assert citizen.get("/team-coverage/1").status_code == 403
