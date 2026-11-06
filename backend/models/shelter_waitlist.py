"""Private queue entries; only explicitly accepted offers become registrations."""
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, Column, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint, text

from backend.database.connection import Base


def utc_now():
    return datetime.now(timezone.utc)


class ShelterWaitlist(Base):
    __tablename__ = "shelter_waitlist"
    __table_args__ = (
        CheckConstraint("party_size > 0 AND party_size <= 1000", name="ck_waitlist_party"),
        CheckConstraint("status IN ('WAITING','OFFERED','ACCEPTED','EXPIRED','CANCELLED')", name="ck_waitlist_status"),
        UniqueConstraint("citizen_id", "request_key", name="uq_waitlist_request"),
        Index("uq_waitlist_active", "shelter_id", "citizen_id", unique=True,
              postgresql_where=text("status IN ('WAITING','OFFERED')"),
              sqlite_where=text("status IN ('WAITING','OFFERED')")),
        Index("ix_waitlist_queue", "shelter_id", "status", "id"),
    )
    id = Column(Integer, primary_key=True)
    shelter_id = Column(Integer, ForeignKey("shelters.id"), nullable=False, index=True)
    citizen_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    party_size = Column(Integer, nullable=False)
    origin_district = Column(String(100), nullable=False)
    origin_locality = Column(String(120), nullable=False)
    origin_latitude = Column(Float)
    origin_longitude = Column(Float)
    contact = Column(String(100))
    note = Column(String(500))
    request_key = Column(String(36), nullable=False)
    request_fingerprint = Column(String(64), nullable=False)
    status = Column(String(10), nullable=False, default="WAITING")
    version = Column(Integer, nullable=False, default=1)
    skip_reason = Column(String(300))
    offered_at = Column(DateTime(timezone=True))
    offer_expires_at = Column(DateTime(timezone=True), index=True)
    registration_id = Column(Integer, ForeignKey("shelter_registrations.id"), unique=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


class ShelterWaitlistEvent(Base):
    __tablename__ = "shelter_waitlist_events"
    __table_args__ = (UniqueConstraint("waitlist_id", "version", name="uq_waitlist_event_version"),)
    id = Column(Integer, primary_key=True)
    waitlist_id = Column(Integer, ForeignKey("shelter_waitlist.id"), nullable=False, index=True)
    status = Column(String(10), nullable=False)
    version = Column(Integer, nullable=False)
    actor_id = Column(Integer, ForeignKey("users.id"))
    note = Column(String(500), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
