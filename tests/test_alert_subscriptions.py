"""Area follows deliver durable, private updates without claiming safety."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from backend.tests.test_auth import api, synthetic_password_hash
from backend.models.alert import Alert
from backend.models.alert_subscription import AlertSubscription, AlertSubscriptionDelivery
from backend.models.communication import Notification
from backend.models.user import User
from backend.services import alert_subscription_service as service


def alert(api, place="ernakulam-aluva", **changes):
    now = datetime.now(timezone.utc)
    response = api.client.post("/api/alerts", headers=api.headers("admin"), json={
        "title": "Synthetic subscribed flood alert", "message": "Synthetic test warning from the administrator.",
        "level": "ORANGE", "place_id": place, "starts_at": (now - timedelta(minutes=1)).isoformat(),
        "expires_at": (now + timedelta(hours=1)).isoformat(), **changes})
    assert response.status_code == 201, response.text
    return response.json()


def follow(api, place="ernakulam-aluva", role="citizen"):
    with api.sessions() as db:
        return service.subscribe(db, db.get(User, api.users[role]), place)[0]


def unfollow(api, subscription, role="citizen"):
    with api.sessions() as db:
        return service.unsubscribe(db, db.get(User, api.users[role]), subscription["id"])


def tick(api, now=None):
    with api.sessions() as db:
        result = service.process_alert_subscriptions(db, now=now)
        db.commit()
        return result


def notes(api, role="citizen"):
    with api.sessions() as db:
        return list(db.scalars(select(Notification).where(Notification.user_id == api.users[role])
                               .order_by(Notification.id)))


def test_follow_current_alert_once_and_deduplicate_overlapping_areas(api):
    alert(api)
    first = follow(api)
    second = follow(api)
    assert first["id"] == second["id"]
    follow(api, "ernakulam")
    assert tick(api)["notifications_created"] == 0
    records = notes(api)
    assert len(records) == 1
    assert records[0].incident_id is None and records[0].target_url == "/alerts"
    assert "Orange alert" in records[0].title
    with api.sessions() as db:
        assert db.scalar(select(func.count()).select_from(AlertSubscriptionDelivery)) == 1
        assert db.scalar(select(func.count()).select_from(AlertSubscription)) == 2


def test_scheduled_start_and_natural_expiry_use_clock_and_retry_is_silent(api):
    now = datetime.now(timezone.utc)
    alert(api, starts_at=(now + timedelta(hours=1)).isoformat(), expires_at=(now + timedelta(hours=2)).isoformat())
    follow(api)
    assert notes(api) == []
    assert tick(api, now + timedelta(minutes=30))["notifications_created"] == 0
    assert tick(api, now + timedelta(hours=1))["notifications_created"] == 1
    assert tick(api, now + timedelta(hours=1, minutes=1))["notifications_created"] == 0
    assert tick(api, now + timedelta(hours=2))["notifications_created"] == 1
    assert tick(api, now + timedelta(hours=3))["notifications_created"] == 0
    assert "Alert ended" in notes(api)[-1].title
    assert "does not confirm" in notes(api)[-1].message


def test_never_delivered_expired_alert_produces_no_end_notice(api):
    now = datetime.now(timezone.utc)
    alert(api, starts_at=(now - timedelta(hours=2)).isoformat(), expires_at=(now - timedelta(hours=1)).isoformat())
    follow(api)
    assert tick(api)["notifications_created"] == 0
    assert notes(api) == []


@pytest.mark.parametrize("place,expected", [("ernakulam", 3), ("ernakulam-aluva", 2), ("thrissur", 0)])
def test_district_follows_include_localities_but_locality_follows_exclude_siblings(api, place, expected):
    alert(api, "ernakulam")
    alert(api, "ernakulam-aluva")
    alert(api, "ernakulam-kochi")
    follow(api, place)
    assert len(notes(api)) == expected


def test_alert_edits_notify_once_without_changing_the_admin_alert(api):
    saved = alert(api)
    follow(api)
    response = api.client.patch(f"/api/alerts/{saved['id']}", headers=api.headers("admin"), json={"level": "RED"})
    assert response.status_code == 200
    assert tick(api)["notifications_created"] == 1
    assert tick(api)["notifications_created"] == 0
    assert "Alert updated" in notes(api)[-1].title and "Red alert" in notes(api)[-1].message
    # Writing an equivalent value changes updated_at, not public alert content.
    assert api.client.patch(f"/api/alerts/{saved['id']}", headers=api.headers("admin"), json={"level": "RED"}).status_code == 200
    assert tick(api)["notifications_created"] == 0
    with api.sessions() as db:
        assert db.get(Alert, saved["id"]).level == "RED"


def test_explicit_expiry_delivers_end_once(api):
    saved = alert(api)
    follow(api)
    assert api.client.post(f"/api/alerts/{saved['id']}/expire", headers=api.headers("admin")).status_code == 200
    assert tick(api)["notifications_created"] == 1
    assert tick(api)["notifications_created"] == 0
    assert len(notes(api)) == 2


def test_alert_moving_to_another_locality_ends_only_the_old_area_coverage(api):
    saved = alert(api)
    follow(api)
    assert api.client.patch(f"/api/alerts/{saved['id']}", headers=api.headers("admin"),
                            json={"place_id": "ernakulam-kochi"}).status_code == 200
    assert tick(api)["notifications_created"] == 1
    assert "coverage changed" in notes(api)[-1].title
    assert api.client.patch(f"/api/alerts/{saved['id']}", headers=api.headers("admin"),
                            json={"place_id": "ernakulam-aluva"}).status_code == 200
    assert tick(api)["notifications_created"] == 1
    assert len(notes(api)) == 3


def test_rescheduling_previously_active_alert_sends_reschedule_then_new_start(api):
    now = datetime.now(timezone.utc)
    saved = alert(api)
    follow(api)
    assert api.client.patch(f"/api/alerts/{saved['id']}", headers=api.headers("admin"), json={
        "starts_at": (now + timedelta(hours=1)).isoformat(), "expires_at": (now + timedelta(hours=2)).isoformat()}).status_code == 200
    assert tick(api)["notifications_created"] == 1
    assert "rescheduled" in notes(api)[-1].title
    assert tick(api, now + timedelta(hours=1))["notifications_created"] == 1
    assert "Orange alert" in notes(api)[-1].title


def test_unfollow_is_private_idempotent_and_silent_then_resubscribe_delivers_current_alert(api):
    saved = alert(api)
    subscription = follow(api)
    with api.sessions() as db:
        with pytest.raises(HTTPException) as error:
            service.unsubscribe(db, db.get(User, api.users["response_team"]), subscription["id"])
        assert error.value.status_code == 404
    unfollow(api, subscription)
    unfollow(api, subscription)
    assert tick(api)["notifications_created"] == 0
    assert len(notes(api)) == 1
    assert follow(api)["id"] == subscription["id"]
    assert len(notes(api)) == 2
    assert api.client.post(f"/api/alerts/{saved['id']}/expire", headers=api.headers("admin")).status_code == 200
    assert tick(api)["notifications_created"] == 1


def test_removing_one_overlapping_follow_keeps_delivery_without_duplicates(api):
    saved = alert(api)
    district = follow(api, "ernakulam")
    follow(api)
    unfollow(api, district)
    assert len(notes(api)) == 1
    assert api.client.post(f"/api/alerts/{saved['id']}/expire", headers=api.headers("admin")).status_code == 200
    assert tick(api)["notifications_created"] == 1


def test_inactive_users_are_not_delivered_and_following_unknown_places_is_rejected(api):
    follow(api)
    with api.sessions() as db:
        user = db.get(User, api.users["citizen"])
        user.active = False
        db.commit()
    alert(api)
    assert tick(api)["processed_users"] == 0
    assert notes(api) == []
    with api.sessions() as db:
        with pytest.raises(HTTPException) as error:
            service.subscribe(db, db.get(User, api.users["admin"]), "invented-place")
        assert error.value.status_code == 422


def test_processing_rollback_does_not_advance_delivery_or_leave_a_notification(api):
    follow(api)
    alert(api)
    with api.sessions() as db:
        assert service.process_alert_subscriptions(db)["notifications_created"] == 1
        db.rollback()
    assert notes(api) == []
    assert tick(api)["notifications_created"] == 1


def test_all_roles_have_separate_subscriptions_and_notifications(api):
    alert(api)
    for role in ("citizen", "admin", "response_team"):
        follow(api, role=role)
    assert all(len(notes(api, role)) == 1 for role in ("citizen", "admin", "response_team"))
    with api.sessions() as db:
        assert len(service.list_subscriptions(db, db.get(User, api.users["citizen"]))) == 1


def test_subscription_api_is_authenticated_own_scoped_and_rejects_privilege_fields(api):
    assert api.client.get("/api/alert-subscriptions").status_code == 401
    assert api.client.post("/api/alert-subscriptions", headers=api.headers("citizen"),
                           json={"place_id": "ernakulam", "user_id": api.users["admin"]}).status_code == 422
    response = api.client.post("/api/alert-subscriptions", headers=api.headers("citizen"), json={"place_id": "ernakulam"})
    assert response.status_code == 201, response.text
    subscription = response.json()
    assert api.client.get("/api/alert-subscriptions", headers=api.headers("response_team")).json() == []
    assert api.client.post(f"/api/alert-subscriptions/{subscription['id']}/unsubscribe",
                           headers=api.headers("response_team")).status_code == 404
    assert api.client.post(f"/api/alert-subscriptions/{subscription['id']}/unsubscribe",
                           headers=api.headers("citizen")).status_code == 200
