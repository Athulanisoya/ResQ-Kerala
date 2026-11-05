"""Citizen shelter joins use the existing tab auth, CSRF and private HTMX views."""
import re

from tests.test_web import clients, login, post


def shelter(admin, **changes):
    response = admin.post("/api/shelters", json={"name": "Synthetic UI shelter", "location": "Aluva school",
        "district": "Ernakulam", "capacity": 2, "occupied": 0, **changes})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_citizen_can_join_from_map_origin_then_find_and_cancel_full_shelter_registration(clients):
    citizen, admin, team = clients
    login(citizen, "citizen"); login(admin, "admin"); login(team, "response_team")
    shelter_id = shelter(admin)
    page = citizen.get(f"/shelters/{shelter_id}/join?origin_district=ernakulam&origin_locality=Aluva&origin_latitude=10.1&origin_longitude=76.3")
    assert page.status_code == 200, page.text
    assert '<option value="ernakulam" selected' in page.text
    assert 'value="Aluva"' in page.text and 'value="10.1"' in page.text
    key = re.search(r'name="request_key" value="([^"]+)"', page.text).group(1)
    response = post(citizen, f"/ui/shelters/{shelter_id}/registrations", request_key=key, party_size="2",
                    origin_district="ernakulam", origin_locality="Aluva", note="<script>synthetic</script>")
    assert response.status_code == 200, response.text
    assert "Your spaces are reserved" in response.text
    assert "&lt;script&gt;synthetic&lt;/script&gt;" in response.text
    assert "resq:shelters-changed" in response.headers["HX-Trigger"]
    assert response.headers["HX-Push-Url"] == f"/shelters/{shelter_id}/join"
    assert "Reserve your group’s spaces" not in response.text
    registrations = citizen.get("/api/shelter-registrations").json()
    assert len(registrations) == 1 and registrations[0]["shelter"]["status"] == "FULL"
    own = citizen.get("/shelter-registrations")
    assert own.status_code == 200 and "Synthetic UI shelter" in own.text and "Cancel reservation" in own.text
    row = registrations[0]
    cancelled = post(citizen, f"/ui/shelters/{shelter_id}/registrations/{row['id']}/status",
                     expected_version="1", status="CANCELLED")
    assert cancelled.status_code == 200 and "Registration updated" in cancelled.text
    assert citizen.get(f"/api/shelters/{shelter_id}").json()["available_capacity"] == 2
    assert team.get(f"/shelters/{shelter_id}/join").status_code == 403


def test_registration_form_errors_retain_location_and_csrf_is_required(clients):
    citizen, admin, _ = clients
    login(citizen, "citizen"); login(admin, "admin")
    shelter_id = shelter(admin)
    page = citizen.get(f"/shelters/{shelter_id}/join")
    key = re.search(r'name="request_key" value="([^"]+)"', page.text).group(1)
    assert citizen.post(f"/ui/shelters/{shelter_id}/registrations", data={"party_size": "1"}).status_code == 403
    invalid = post(citizen, f"/ui/shelters/{shelter_id}/registrations", request_key=key, party_size="1",
                   origin_district="ernakulam", origin_locality="Keep this locality", origin_latitude="NaN", origin_longitude="76")
    assert invalid.status_code == 422
    assert 'value="Keep this locality"' in invalid.text
    assert 'value="' + key + '"' in invalid.text
    assert citizen.get("/api/shelter-registrations").json() == []


def test_admin_reception_can_confirm_arrival_and_departure_through_forms(clients):
    citizen, admin, _ = clients
    login(citizen, "citizen"); login(admin, "admin")
    shelter_id = shelter(admin)
    page = citizen.get(f"/shelters/{shelter_id}/join")
    key = re.search(r'name="request_key" value="([^"]+)"', page.text).group(1)
    post(citizen, f"/ui/shelters/{shelter_id}/registrations", request_key=key, party_size="1",
         origin_district="ernakulam", origin_locality="Aluva")
    row = citizen.get("/api/shelter-registrations").json()[0]
    reception = admin.get(f"/shelters/{shelter_id}/join")
    assert reception.status_code == 200 and "Confirm arrival" in reception.text and "Test citizen" in reception.text
    arrived = post(admin, f"/ui/shelters/{shelter_id}/registrations/{row['id']}/status",
                   expected_version="1", status="ARRIVED", note="Synthetic arrival")
    assert arrived.status_code == 200 and "Record departure" in arrived.text
    assert "Confirm arrival" not in arrived.text
    departed = post(admin, f"/ui/shelters/{shelter_id}/registrations/{row['id']}/status",
                    expected_version="2", status="DEPARTED")
    assert departed.status_code == 200
    assert citizen.get(f"/api/shelters/{shelter_id}").json()["occupied"] == 0
