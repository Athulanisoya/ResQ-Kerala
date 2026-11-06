"""Follow screens use the existing protected HTMX and CSRF workflow."""
from tests.test_web import clients, login, post
from web.app import CSRF_COOKIE


def test_follow_area_then_unfollow_and_open_private_notifications(clients):
    citizen, admin, team = clients
    login(citizen, "citizen"); login(admin, "admin"); login(team, "response_team")
    page = citizen.get("/alert-subscriptions")
    assert page.status_code == 200
    assert "Follow alert areas" in page.text and "No areas followed yet" in page.text
    followed = post(citizen, "/ui/alert-subscriptions", place_id="ernakulam-aluva")
    assert followed.status_code == 200, followed.text
    assert "Area followed" in followed.text and "Unfollow Aluva" in followed.text
    assert followed.headers["HX-Push-Url"] == "/alert-subscriptions"
    assert "resq:refresh-updates" in followed.headers["HX-Trigger"]
    assert "No areas followed yet" in team.get("/alert-subscriptions").text
    record = citizen.get("/api/alert-subscriptions").json()[0]
    assert post(team, f"/ui/alert-subscriptions/{record['id']}/unsubscribe").status_code == 404
    unfollowed = post(citizen, f"/ui/alert-subscriptions/{record['id']}/unsubscribe")
    assert unfollowed.status_code == 200 and "Area unfollowed" in unfollowed.text
    assert "No areas followed yet" in unfollowed.text


def test_follow_form_rejects_cross_origin_and_missing_csrf_without_mutating(clients):
    citizen, _, _ = clients
    login(citizen, "citizen")
    citizen.get("/alert-subscriptions")
    assert citizen.post("/ui/alert-subscriptions", data={"place_id": "ernakulam"}).status_code == 403
    assert citizen.post("/ui/alert-subscriptions", data={"_csrf": citizen.cookies.get(CSRF_COOKIE), "place_id": "ernakulam"},
                        headers={"Origin": "https://other.example", "HX-Request": "true"}).status_code == 403
    assert citizen.get("/api/alert-subscriptions").json() == []


def test_unknown_follow_area_is_validated_and_not_injected_into_html(clients):
    citizen, _, _ = clients
    login(citizen, "citizen")
    citizen.get("/alert-subscriptions")
    result = post(citizen, "/ui/alert-subscriptions", place_id="<script>synthetic</script>")
    assert result.status_code == 422
    assert "<script>synthetic</script>" not in result.text
    assert citizen.get("/api/alert-subscriptions").json() == []
