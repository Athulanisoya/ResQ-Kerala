"""Private in-app updates and retained citizen clarification correspondence."""

from datetime import datetime, timezone

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint

from backend.database.connection import Base


def utc_now():
    return datetime.now(timezone.utc)


class Notification(Base):
    __tablename__ = "incident_notifications"
    __table_args__ = (UniqueConstraint("user_id", "event_key", name="uq_notification_user_event"),)

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    incident_id = Column(Integer, ForeignKey("incident_reports.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(120), nullable=False)
    message = Column(Text, nullable=False)
    event_key = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    read_at = Column(DateTime(timezone=True), nullable=True)


class IncidentClarification(Base):
    __tablename__ = "incident_clarifications"
    __table_args__ = (CheckConstraint("status IN ('OPEN', 'ANSWERED', 'CANCELLED')", name="ck_clarification_status"),)

    id = Column(Integer, primary_key=True)
    incident_id = Column(Integer, ForeignKey("incident_reports.id", ondelete="CASCADE"), nullable=False, index=True)
    asked_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    question = Column(Text, nullable=False)
    required = Column(Boolean, nullable=False, default=True)
    status = Column(String(20), nullable=False, default="OPEN")
    asked_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    replied_at = Column(DateTime(timezone=True), nullable=True)
    cancelled_at = Column(DateTime(timezone=True), nullable=True)


class ClarificationReply(Base):
    __tablename__ = "incident_clarification_replies"
    __table_args__ = (UniqueConstraint("clarification_id", name="uq_clarification_retained_reply"),)

    id = Column(Integer, primary_key=True)
    clarification_id = Column(Integer, ForeignKey("incident_clarifications.id", ondelete="CASCADE"), nullable=False, index=True)
    replied_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    message = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
