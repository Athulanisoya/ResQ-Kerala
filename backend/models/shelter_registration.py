"""Private shelter reservations and immutable reception events."""
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, Column, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint, text

from backend.database.connection import Base


def utc_now():
    return datetime.now(timezone.utc)


class ShelterRegistration(Base):
    __tablename__ = "shelter_registrations"
    __table_args__ = (
        CheckConstraint("party_size > 0 AND party_size <= 1000", name="ck_shelter_registration_party"),
        CheckConstraint("status IN ('RESERVED','ARRIVED','CANCELLED','DEPARTED')", name="ck_shelter_registration_status"),
        UniqueConstraint("citizen_id", "request_key", name="uq_shelter_registration_request"),
        Index("uq_shelter_registration_active", "shelter_id", "citizen_id", unique=True,
              postgresql_where=text("status IN ('RESERVED','ARRIVED')"),
              sqlite_where=text("status IN ('RESERVED','ARRIVED')")),
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
    status = Column(String(10), nullable=False, default="RESERVED")
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


class ShelterRegistrationEvent(Base):
    __tablename__ = "shelter_registration_events"
    __table_args__ = (UniqueConstraint("registration_id", "version", name="uq_shelter_registration_event_version"),)
    id = Column(Integer, primary_key=True)
    registration_id = Column(Integer, ForeignKey("shelter_registrations.id"), nullable=False, index=True)
    status = Column(String(10), nullable=False)
    version = Column(Integer, nullable=False)
    actor_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    note = Column(String(500))
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
