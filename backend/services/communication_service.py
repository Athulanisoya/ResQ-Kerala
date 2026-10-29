"""Citizen updates share the incident transaction and never send externally."""

from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from backend.models.communication import ClarificationReply, IncidentClarification, Notification
from backend.models.incident import Incident, IncidentStatusHistory
from backend.models.user import Role, User


TERMINAL_STATUSES = {"CLOSED", "CANCELLED", "REJECTED"}


def utc_now():
    return datetime.now(timezone.utc)


def iso(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def notify_incident(db: Session, incident: Incident, title: str, message: str,
                    event_key: str | None = None, *, extra_team_ids=()) -> list[Notification]:
    """Flush private updates in the caller's transaction; NEVER commit here.

    The parent lock serializes deduplication against the same incident. A key is
    scoped to that incident, and the unique constraint is a second safeguard.
    """
    db.execute(select(Incident.id).where(Incident.id == incident.id).with_for_update())
    scoped_key = f"incident:{incident.id}:{event_key}" if event_key else None
    if scoped_key and len(scoped_key) > 255:
        raise ValueError("Notification event key is too long")
    if not title.strip() or len(title) > 120 or not message.strip() or len(message) > 4000:
        raise ValueError("Notification text is invalid")
    recipients = [User.id == incident.user_id, User.role == Role.ADMIN]
    if incident.assigned_team_id is not None:
        recipients.append((User.role == Role.RESPONSE_TEAM) & (User.team_id == incident.assigned_team_id))
    # Explicit support teams receive only the relief event that concerns them;
    # this opt-in never grants access to later incident correspondence.
    if extra_team_ids:
        recipients.append((User.role == Role.RESPONSE_TEAM) & (User.team_id.in_(tuple(extra_team_ids))))
    user_ids = list(db.scalars(select(User.id).where(User.active.is_(True), or_(*recipients))))
    existing = set()
    if scoped_key:
        existing = set(db.scalars(select(Notification.user_id).where(Notification.event_key == scoped_key)))
    records = []
    for user_id in user_ids:
        if user_id in existing:
            continue
        record = Notification(user_id=user_id, incident_id=incident.id, title=title,
                              message=message, event_key=scoped_key)
        db.add(record)
        records.append(record)
    db.flush()
    return records


def notification_payload(record: Notification):
    operational = any(part in (record.event_key or "") for part in (":relief:", ":relief-delivery:"))
    return {"id": record.id, "incident_id": record.incident_id,
            "title": record.title, "message": record.message,
            "is_read": record.read_at is not None, "created_at": iso(record.created_at),
            "read_at": iso(record.read_at),
            "target_url": "/operations" if operational else f"/reports/{record.incident_id}"}


def list_notifications(db: Session, user_id: int, limit: int = 30, before_id: int | None = None):
    query = select(Notification).where(Notification.user_id == user_id)
    if before_id is not None:
        query = query.where(Notification.id < before_id)
    records = list(db.scalars(query.order_by(Notification.id.desc()).limit(limit + 1)))
    has_more = len(records) > limit
    records = records[:limit]
    unread = db.scalar(select(func.count(Notification.id)).where(
        Notification.user_id == user_id, Notification.read_at.is_(None)))
    return {"unread_count": unread, "notifications": [notification_payload(item) for item in records],
            "next_before_id": records[-1].id if has_more else None}


def mark_notification_read(db: Session, user_id: int, notification_id: int):
    try:
        record = db.scalar(select(Notification).where(
            Notification.id == notification_id, Notification.user_id == user_id).with_for_update())
        if record is None:
            raise HTTPException(status_code=404, detail="Notification not found")
        if record.read_at is None:
            record.read_at = utc_now()
        db.commit()
        return notification_payload(record)
    except Exception:
        db.rollback()
        raise


def mark_all_notifications_read(db: Session, user_id: int):
    try:
        result = db.execute(update(Notification).where(
            Notification.user_id == user_id, Notification.read_at.is_(None)).values(read_at=utc_now()))
        db.commit()
        return {"updated_count": result.rowcount, "unread_count": 0}
    except Exception:
        db.rollback()
        raise


def clarification_payload(db: Session, record: IncidentClarification):
    replies = list(db.scalars(select(ClarificationReply).where(
        ClarificationReply.clarification_id == record.id).order_by(ClarificationReply.id)))
    return {"id": record.id, "incident_id": record.incident_id, "question": record.question,
            "required": record.required, "status": record.status, "asked_at": iso(record.asked_at),
            "replied_at": iso(record.replied_at), "cancelled_at": iso(record.cancelled_at),
            "replies": [{"id": reply.id, "message": reply.message,
                         "created_at": iso(reply.created_at)} for reply in replies]}


def list_clarifications(db: Session, incident_id: int):
    return [clarification_payload(db, record) for record in db.scalars(
        select(IncidentClarification).where(IncidentClarification.incident_id == incident_id)
        .order_by(IncidentClarification.id))]


def locked_incident(db: Session, incident_id: int):
    incident = db.scalar(select(Incident).where(Incident.id == incident_id).with_for_update()
                         .execution_options(populate_existing=True))
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return incident


def require_open_incident(incident: Incident):
    if incident.status in TERMINAL_STATUSES:
        raise HTTPException(status_code=409, detail="This incident is closed to further correspondence")


def ask_clarification(db: Session, incident_id: int, admin: User, question: str, required: bool = True):
    try:
        if admin.role != Role.ADMIN:
            raise HTTPException(status_code=403, detail="Only administrators can request clarification")
        incident = locked_incident(db, incident_id)
        require_open_incident(incident)
        record = IncidentClarification(incident_id=incident.id, asked_by_id=admin.id,
                                       question=question, required=required)
        db.add(record)
        db.flush()
        db.add(IncidentStatusHistory(incident_id=incident.id, status="CLARIFICATION_REQUESTED",
                                     note=f"Clarification #{record.id} requested: {question}"))
        notify_incident(db, incident, "Clarification requested", question,
                        event_key=f"clarification:{record.id}:requested")
        db.commit()
        return clarification_payload(db, record)
    except Exception:
        db.rollback()
        raise


def reply_to_clarification(db: Session, clarification_id: int, user: User, message: str):
    try:
        initial = db.get(IncidentClarification, clarification_id)
        if initial is None:
            raise HTTPException(status_code=404, detail="Clarification not found")
        incident = locked_incident(db, initial.incident_id)
        if user.role != Role.CITIZEN or incident.user_id != user.id:
            raise HTTPException(status_code=403, detail="Only the reporting citizen can reply")
        record = db.scalar(select(IncidentClarification).where(IncidentClarification.id == clarification_id)
                           .with_for_update().execution_options(populate_existing=True))
        previous = db.scalar(select(ClarificationReply).where(ClarificationReply.clarification_id == record.id))
        if previous is not None:
            if previous.message != message:
                raise HTTPException(status_code=409, detail="This clarification already has a retained reply")
            # A lost response can be retried even after final closure. Returning
            # this immutable receipt adds no correspondence or notification.
            return clarification_payload(db, record)
        require_open_incident(incident)
        if record.status != "OPEN":
            raise HTTPException(status_code=409, detail="This clarification no longer accepts replies")
        reply = ClarificationReply(clarification_id=record.id, replied_by_id=user.id, message=message)
        db.add(reply)
        record.status = "ANSWERED"
        record.replied_at = utc_now()
        db.add(IncidentStatusHistory(incident_id=incident.id, status="CLARIFICATION_REPLIED",
                                     note=f"Citizen replied to clarification #{record.id}"))
        notify_incident(db, incident, "Citizen clarification received", message,
                        event_key=f"clarification:{record.id}:replied")
        db.commit()
        return clarification_payload(db, record)
    except Exception:
        db.rollback()
        raise


def cancel_clarification(db: Session, clarification_id: int, admin: User):
    try:
        if admin.role != Role.ADMIN:
            raise HTTPException(status_code=403, detail="Only administrators can cancel clarification")
        initial = db.get(IncidentClarification, clarification_id)
        if initial is None:
            raise HTTPException(status_code=404, detail="Clarification not found")
        incident = locked_incident(db, initial.incident_id)
        require_open_incident(incident)
        record = db.scalar(select(IncidentClarification).where(IncidentClarification.id == clarification_id)
                           .with_for_update().execution_options(populate_existing=True))
        if record.status == "ANSWERED":
            raise HTTPException(status_code=409, detail="Answered clarifications are retained")
        if record.status == "OPEN":
            record.status = "CANCELLED"
            record.cancelled_at = utc_now()
            db.add(IncidentStatusHistory(incident_id=incident.id, status="CLARIFICATION_CANCELLED",
                                         note=f"Clarification #{record.id} cancelled by an administrator"))
            notify_incident(db, incident, "Clarification cancelled",
                            f"Clarification #{record.id} no longer requires a reply.",
                            event_key=f"clarification:{record.id}:cancelled")
        db.commit()
        return clarification_payload(db, record)
    except Exception:
        db.rollback()
        raise


def close_incident(db: Session, incident_id: int, admin: User, note: str | None = None):
    from backend.services.operations_service import unfinished_relief

    try:
        if admin.role != Role.ADMIN:
            raise HTTPException(status_code=403, detail="Only administrators can close incidents")
        incident = locked_incident(db, incident_id)
        if incident.status != "RESOLVED":
            raise HTTPException(status_code=409, detail="Only a resolved incident can be closed")
        if unfinished_relief(db, incident.id):
            raise HTTPException(status_code=409, detail="Complete outstanding relief before closure")
        unanswered = db.scalar(select(IncidentClarification.id).where(
            IncidentClarification.incident_id == incident.id, IncidentClarification.required.is_(True),
            IncidentClarification.status == "OPEN").limit(1))
        if unanswered is not None:
            raise HTTPException(status_code=409, detail="Answer or cancel required clarifications before closure")
        incident.status = "CLOSED"
        closed_at = utc_now()
        db.add(IncidentStatusHistory(incident_id=incident.id, status="CLOSED",
                                     note=note or "Administrator confirmed final closure", created_at=closed_at))
        notify_incident(db, incident, "Incident closed", note or "An administrator confirmed final closure of your report.",
                        event_key="closed")
        db.commit()
        return {"incident_id": incident.id, "status": incident.status, "closed_at": iso(closed_at)}
    except Exception:
        db.rollback()
        raise
