"""Administrator policy, reminder deduplication and durable worker heartbeat."""
from datetime import datetime, timezone

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Integer, String, Text

from backend.database.connection import Base


def utc_now():
    return datetime.now(timezone.utc)


class AutomationPolicy(Base):
    __tablename__ = "automation_policy"
    __table_args__ = (CheckConstraint("id = 1 AND stale_minutes BETWEEN 1 AND 1440 AND reminder_minutes BETWEEN 5 AND 1440 AND escalation_minutes > stale_minutes AND escalation_minutes <= 10080 AND waitlist_offer_minutes BETWEEN 1 AND 1440", name="ck_automation_policy"),)
    id = Column(Integer, primary_key=True, default=1)
    stale_minutes = Column(Integer, nullable=False)
    reminder_minutes = Column(Integer, nullable=False)
    escalation_minutes = Column(Integer, nullable=False)
    waitlist_offer_minutes = Column(Integer, nullable=False)
    version = Column(Integer, nullable=False, default=1)
    updated_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


class ShelterReminderState(Base):
    __tablename__ = "shelter_reminder_state"
    shelter_id = Column(Integer, ForeignKey("shelters.id"), primary_key=True)
    confirmation_key = Column(String(100), nullable=False)
    sequence = Column(Integer, nullable=False, default=0)
    last_notified_at = Column(DateTime(timezone=True))
    last_escalated_at = Column(DateTime(timezone=True))


class AutomationRuntime(Base):
    __tablename__ = "automation_runtime"
    __table_args__ = (CheckConstraint("id = 1", name="ck_automation_runtime"),)
    id = Column(Integer, primary_key=True, default=1)
    checked_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    last_success_at = Column(DateTime(timezone=True))
    has_error = Column(Boolean, nullable=False, default=False)
    summary = Column(Text, nullable=False, default="{}")
