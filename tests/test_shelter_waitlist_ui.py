"""Waitlist forms use tab authentication, CSRF and private reception views."""
import re

from tests.test_web import clients, login, post


def create_shelter(admin, **changes):
    response = admin.post("/api/shelters", json={"name": "Synthetic UI waitlist shelter", "location": "Aluva test hall",
        "district": "Ernakulam", "capacity": 3, "occupied": 0, **changes})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_join_offer_and_explicit_accept_creates_reservation_with_private_history(clients):
    citizen, admin, team = clients
    login(citizen, "citizen"); login(admin, "admin"); login(team, "response_team")
    shelter_id = create_shelter(admin)
    page = citizen.get(f"/shelters/{shelter_id}/waitlist?origin_district=ernakulam&origin_locality=Aluva")
    assert page.status_code == 200, page.text
    assert '<option value="ernakulam" selected' in page.text and 'value="Aluva"' in page.text
    assert f'hx-get="/ui/shelters/{shelter_id}/waitlist/records"' in page.text
    key = re.search(r'name="request_key" value="([^"]+)"', page.text).group(1)
    offered = post(citizen, f"/ui/shelters/{shelter_id}/waitlist", request_key=key,
        party_size="2", origin_district="ernakulam", origin_locality="Aluva", note="<script>synthetic</script>")
    assert offered.status_code == 200, offered.text
    assert "Accept offer and reserve spaces" in offered.text and "&lt;script&gt;synthetic&lt;/script&gt;" in offered.text
    assert "Automatic" in offered.text
    assert offered.headers["HX-Push-Url"] == f"/shelters/{shelter_id}/waitlist"
    row = citizen.get("/api/shelter-waitlist").json()[0]
    assert row["status"] == "OFFERED" and citizen.get("/api/shelter-registrations").json() == []
    accepted = post(citizen, f"/ui/shelters/{shelter_id}/waitlist/{row['id']}/accept", expected_version=str(row["version"]))
    assert accepted.status_code == 200, accepted.text
    assert "Your offer became reservation" in accepted.text and "View reservation and reception updates" in accepted.text
    assert "resq:shelters-changed" in accepted.headers["HX-Trigger"]
    assert citizen.get("/api/shelter-registrations").json()[0]["status"] == "RESERVED"
    assert "Test citizen" not in team.get(f"/shelters/{shelter_id}/waitlist").text
    assert team.get(f"/shelters/{shelter_id}/waitlist").status_code == 403
    assert "Synthetic UI waitlist shelter" in citizen.get("/shelter-waitlist").text
    assert "Your waiting-list entries" in citizen.get("/ui/shelter-waitlist/records").text
    assert team.get(f"/ui/shelters/{shelter_id}/waitlist/records").status_code == 403


def test_waiting_list_errors_keep_drafts_and_require_csrf(clients):
    citizen, admin, _ = clients
    login(citizen, "citizen"); login(admin, "admin")
    shelter_id = create_shelter(admin, occupied=3)
    page = citizen.get(f"/shelters/{shelter_id}/waitlist")
    key = re.search(r'name="request_key" value="([^"]+)"', page.text).group(1)
    assert citizen.post(f"/ui/shelters/{shelter_id}/waitlist", data={"party_size": "1"}).status_code == 403
    invalid = post(citizen, f"/ui/shelters/{shelter_id}/waitlist", request_key=key, party_size="1",
        origin_district="ernakulam", origin_locality="Keep this locality", origin_latitude="NaN", origin_longitude="76")
    assert invalid.status_code == 422 and 'value="Keep this locality"' in invalid.text
    queued = post(citizen, f"/ui/shelters/{shelter_id}/waitlist", request_key=key, party_size="1",
        origin_district="ernakulam", origin_locality="Keep this locality")
    assert queued.status_code == 200 and "Waiting for 1 spaces together" in queued.text
    row = citizen.get("/api/shelter-waitlist").json()[0]
    cancelled = post(citizen, f"/ui/shelters/{shelter_id}/waitlist/{row['id']}/cancel", expected_version=str(row["version"]))
    assert cancelled.status_code == 200 and "Waiting-list entry cancelled" in cancelled.text


def test_staff_cannot_accept_for_citizen_and_action_url_must_match_shelter(clients):
    citizen, admin, _ = clients
    login(citizen, "citizen"); login(admin, "admin")
    shelter_id = create_shelter(admin)
    page = citizen.get(f"/shelters/{shelter_id}/waitlist")
    key = re.search(r'name="request_key" value="([^"]+)"', page.text).group(1)
    post(citizen, f"/ui/shelters/{shelter_id}/waitlist", request_key=key, party_size="1", origin_district="ernakulam", origin_locality="Aluva")
    row = citizen.get("/api/shelter-waitlist").json()[0]
    roster = admin.get(f"/shelters/{shelter_id}/waitlist")
    assert roster.status_code == 200 and "Test citizen" in roster.text
    assert "Accept offer and reserve spaces" not in roster.text
    assert post(admin, f"/ui/shelters/{shelter_id}/waitlist/{row['id']}/accept", expected_version=str(row["version"])).status_code == 403
    other = create_shelter(admin)
    assert post(citizen, f"/ui/shelters/{other}/waitlist/{row['id']}/accept", expected_version=str(row["version"])).status_code == 403
