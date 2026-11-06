"""Following an area delivers admin alert changes, never inferred safety claims."""
from datetime import datetime, timedelta, timezone
import hashlib
import json

from fastapi import HTTPException
from sqlalchemy import or_, select

from backend.ai.location_extractor import get_place
from backend.models.alert import Alert
from backend.models.alert_subscription import AlertSubscription, AlertSubscriptionDelivery
from backend.models.user import User
from backend.services.alert_service import utc


def _locked_user(db, user_id):
    user = db.scalar(select(User).where(User.id == user_id).with_for_update()
                     .execution_options(populate_existing=True))
    if user is None or not user.active:
        raise HTTPException(403, "An active account is required to follow alert areas.")
    return user


def subscription_view(row):
    place = get_place(row.place_id)
    return {"id": row.id, "place_id": row.place_id, "enabled": row.enabled,
            "place_name": place.name if place else row.place_id,
            "district": place.district if place else None,
            "place_kind": place.kind if place else None,
            "created_at": row.created_at, "updated_at": row.updated_at}


def list_subscriptions(db, user):
    return [subscription_view(row) for row in db.scalars(select(AlertSubscription).where(
        AlertSubscription.user_id == user.id, AlertSubscription.enabled.is_(True))
        .order_by(AlertSubscription.place_id))]


def subscribe(db, user, place_id):
    _locked_user(db, user.id)
    if get_place(place_id) is None:
        raise HTTPException(422, "Choose a recognised district or locality from the place list.")
    row = db.scalar(select(AlertSubscription).where(AlertSubscription.user_id == user.id,
                                                   AlertSubscription.place_id == place_id))
    created = row is None
    if row is None:
        row = AlertSubscription(user_id=user.id, place_id=place_id, enabled=True)
        db.add(row)
    elif not row.enabled:
        row.enabled = True
        row.updated_at = datetime.now(timezone.utc)
    db.flush()
    process_alert_subscriptions(db, user_id=user.id)
    db.commit()
    return subscription_view(row), created


def unsubscribe(db, user, subscription_id):
    _locked_user(db, user.id)
    row = db.scalar(select(AlertSubscription).where(AlertSubscription.id == subscription_id,
                                                   AlertSubscription.user_id == user.id))
    if row is None:
        raise HTTPException(404, "Followed area not found")
    if row.enabled:
        row.enabled = False
        row.updated_at = datetime.now(timezone.utc)
        db.flush()
        # Silently stop delivery state no longer covered by remaining follows.
        # Unfollowing is never announced as an alert ending.
        enabled = [get_place(item.place_id) for item in db.scalars(select(AlertSubscription).where(
            AlertSubscription.user_id == user.id, AlertSubscription.enabled.is_(True)))]
        for delivery in db.scalars(select(AlertSubscriptionDelivery).where(
                AlertSubscriptionDelivery.user_id == user.id, AlertSubscriptionDelivery.active.is_(True))):
            alert = db.get(Alert, delivery.alert_id)
            if alert is None or not any(place and _covers(place, alert) for place in enabled):
                delivery.active = False
                delivery.updated_at = datetime.now(timezone.utc)
    db.commit()
    return subscription_view(row)


def _covers(place, alert):
    return (place.district_id == alert.district_id and
            (place.kind == "district" or alert.place_kind == "district" or place.id == alert.place_id))


def _fingerprint(alert):
    values = {name: getattr(alert, name) for name in
              ("title", "message", "level", "place_id", "place_name", "place_kind", "district_id")}
    values.update(starts_at=utc(alert.starts_at).isoformat(), expires_at=utc(alert.expires_at).isoformat())
    return hashlib.sha256(json.dumps(values, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _display_time(value):
    return utc(value).astimezone(timezone(timedelta(hours=5, minutes=30))).strftime("%d %b %Y, %H:%M IST")


def _emit(db, user_id, alert, delivery, event, now):
    from backend.services.automation_notifications import notify_user
    if event == "started":
        title = f"{alert.level.title()} alert for {alert.place_name}"
        detail = f"{alert.title}\n{alert.message[:2800]}"
    elif event == "updated":
        title = f"Alert updated: {alert.place_name}"
        detail = f"{alert.level.title()} alert · {alert.title}\n{alert.message[:2800]}"
    elif event == "coverage-ended":
        title = f"Alert coverage changed: {alert.place_name}"
        detail = "An alert previously covering a followed area now covers a different area. Check current alert coverage."
    elif event == "rescheduled":
        title = f"Alert rescheduled: {alert.place_name}"
        detail = f"{alert.title} is scheduled to start at {_display_time(alert.starts_at)}."
    else:
        title = f"Alert ended: {alert.place_name}"
        detail = f"{alert.title} is no longer active in this application. This does not confirm that the area is safe."
    message = (f"{detail}\nAdministrator-issued alert #{alert.id}. Coverage: {alert.place_name} ({alert.place_kind}). "
               f"Current alert end: {_display_time(alert.expires_at)}. Check the alert list before travelling.")
    record = notify_user(db, user_id, title[:120], message, f"area-alert:{user_id}:{alert.id}:{delivery.sequence}:{event}", "/alerts")
    return int(record is not None)


def process_alert_subscriptions(db, *, now=None, user_id=None):
    """Process durable alert state in the caller's transaction; never commit.

    Lock users in a stable order. Subscription edits take the same lock, so
    overlapping follows, repeated workers and unfollows cannot double-deliver.
    Delivery state only advances atomically with its notification rows.
    """
    now = utc(now or datetime.now(timezone.utc))
    query = select(User).where(User.active.is_(True))
    if user_id is not None:
        query = query.where(User.id == user_id)
    else:
        query = query.where(User.id.in_(select(AlertSubscription.user_id).where(AlertSubscription.enabled.is_(True))))
    # Background work skips accounts being edited in another transaction. It
    # catches them on the next tick rather than blocking core administration.
    users = db.scalars(query.order_by(User.id).with_for_update(skip_locked=user_id is None)
                       .execution_options(populate_existing=True)).all()
    total = 0
    for user in users:
        places = [get_place(row.place_id) for row in db.scalars(select(AlertSubscription).where(
            AlertSubscription.user_id == user.id, AlertSubscription.enabled.is_(True)))]
        places = [place for place in places if place]
        prior = {row.alert_id: row for row in db.scalars(select(AlertSubscriptionDelivery).where(
            AlertSubscriptionDelivery.user_id == user.id))}
        filters = [Alert.district_id.in_({place.district_id for place in places})]
        if prior:
            filters.append(Alert.id.in_(prior))
        for alert in db.scalars(select(Alert).where(or_(*filters)).order_by(Alert.id)):
            matches = [place.id for place in places if _covers(place, alert)]
            active = alert.expired_at is None and utc(alert.starts_at) <= now < utc(alert.expires_at)
            delivery = prior.get(alert.id)
            fingerprint = _fingerprint(alert)
            if active and matches:
                event = "started" if delivery is None or not delivery.active else "updated" if delivery.fingerprint != fingerprint else None
                if delivery is None:
                    delivery = AlertSubscriptionDelivery(user_id=user.id, alert_id=alert.id, fingerprint=fingerprint,
                                                         active=False, sequence=0, matched_places="[]")
                    db.add(delivery)
                if event:
                    delivery.sequence += 1
                    total += _emit(db, user.id, alert, delivery, event, now)
                delivery.active = True
                delivery.fingerprint = fingerprint
                delivery.matched_places = json.dumps(sorted(matches))
                delivery.updated_at = now
            elif delivery is not None and delivery.active:
                previous_matches = set(json.loads(delivery.matched_places))
                still_followed = previous_matches.intersection(place.id for place in places)
                if still_followed:
                    event = ("coverage-ended" if not matches else "rescheduled" if alert.expired_at is None
                             and utc(alert.starts_at) > now else "ended")
                    delivery.sequence += 1
                    total += _emit(db, user.id, alert, delivery, event, now)
                delivery.active = False
                delivery.fingerprint = fingerprint
                delivery.updated_at = now
    db.flush()
    return {"processed_users": len(users), "notifications_created": total}
