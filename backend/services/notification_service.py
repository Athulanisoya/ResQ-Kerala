from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.notification import Notification


def create_notification(
    db: Session,
    user_id: int,
    message: str,
    notification_type: str,
    incident_id: int | None = None,
) -> Notification:
    """Create and save a notification for a user."""

    notification = Notification(
        user_id=user_id,
        incident_id=incident_id,
        message=message,
        notification_type=notification_type,
    )

    db.add(notification)
    db.commit()
    db.refresh(notification)

    return notification


def get_user_notifications(
    db: Session,
    user_id: int,
    unread_only: bool = False,
) -> list[Notification]:
    """Return notifications belonging to one user."""

    query = select(Notification).where(
        Notification.user_id == user_id
    )

    if unread_only:
        query = query.where(Notification.is_read.is_(False))

    query = query.order_by(
        Notification.created_at.desc(),
        Notification.id.desc(),
    )

    return list(db.scalars(query).all())


def mark_notification_as_read(
    db: Session,
    notification_id: int,
    user_id: int,
) -> Notification | None:
    """Mark a notification as read if it belongs to the user."""

    query = select(Notification).where(
        Notification.id == notification_id,
        Notification.user_id == user_id,
    )

    notification = db.scalars(query).first()

    if notification is None:
        return None

    notification.is_read = True

    db.commit()
    db.refresh(notification)

    return notification


def mark_all_notifications_as_read(
    db: Session,
    user_id: int,
) -> int:
    """Mark all unread notifications belonging to a user as read."""

    notifications = db.scalars(
        select(Notification).where(
            Notification.user_id == user_id,
            Notification.is_read.is_(False),
        )
    ).all()

    for notification in notifications:
        notification.is_read = True

    db.commit()

    return len(notifications)