"""Private non-incident notifications in the caller's transaction."""
import re
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend.models.communication import Notification
from backend.models.user import User


TARGET = re.compile(r"/(?:alerts|alert-subscriptions|volunteers|family-safety|shelter-waitlist|shelter-registrations|shelters(?:/[1-9][0-9]*/(?:join|waitlist))?)")


def notify_user(db, user_id, title, message, event_key, target_url):
    """Flush, never commit; a unique event key makes retries harmless."""
    parsed = urlsplit(target_url)
    if (parsed.scheme or parsed.netloc or parsed.fragment or not TARGET.fullmatch(parsed.path)
            or len(target_url) > 600 or any(ord(char) < 32 for char in target_url)):
        raise ValueError("Notification target must be a supported internal page")
    if (not title.strip() or len(title) > 120 or not message.strip() or len(message) > 4000
            or not event_key or len(event_key) > 255):
        raise ValueError("Invalid automation notification")
    user = db.get(User, user_id)
    if user is None or not user.active:
        return None
    existing = db.scalar(select(Notification.id).where(Notification.user_id == user_id, Notification.event_key == event_key))
    if existing is not None:
        return None
    try:
        with db.begin_nested():
            record = Notification(user_id=user_id, incident_id=None, title=title, message=message,
                                  event_key=event_key, target_url=target_url)
            db.add(record)
            db.flush()
        return record
    except IntegrityError:
        if db.scalar(select(Notification.id).where(Notification.user_id == user_id, Notification.event_key == event_key)) is not None:
            return None
        raise
