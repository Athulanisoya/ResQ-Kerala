"""Volunteer membership is reviewed separately from account privileges."""
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint

from backend.database.connection import Base


def now():
    return datetime.now(timezone.utc)


class VolunteerApplication(Base):
    __tablename__ = 'volunteer_applications'
    __table_args__ = (CheckConstraint("status IN ('PENDING','APPROVED','REJECTED','SUSPENDED')", name='ck_volunteer_application_status'),
                      CheckConstraint('version > 0', name='ck_volunteer_application_version'))
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), unique=True, nullable=False)
    district_id = Column(String(100), nullable=False)
    locality_id = Column(String(100))
    ward = Column(String(120), nullable=False)
    skills = Column(JSON, nullable=False, default=list)
    availability = Column(String(1000), nullable=False)
    status = Column(String(20), nullable=False, default='PENDING')
    consent_at = Column(DateTime(timezone=True), nullable=False)
    review_note = Column(String(1000), nullable=False, default='')
    reviewed_by_id = Column(Integer, ForeignKey('users.id'))
    reviewed_at = Column(DateTime(timezone=True))
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime(timezone=True), nullable=False, default=now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=now)


class VolunteerApplicationEvent(Base):
    __tablename__ = 'volunteer_application_events'
    id = Column(Integer, primary_key=True)
    application_id = Column(Integer, ForeignKey('volunteer_applications.id'), nullable=False, index=True)
    actor_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    action = Column(String(30), nullable=False)
    version = Column(Integer, nullable=False)
    note = Column(String(1000), nullable=False, default='')
    snapshot = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=now)


class VolunteerShift(Base):
    __tablename__ = 'volunteer_shifts'
    __table_args__ = (CheckConstraint('slots BETWEEN 1 AND 1000', name='ck_volunteer_shift_slots'),
                      CheckConstraint('ends_at > starts_at', name='ck_volunteer_shift_interval'),
                      CheckConstraint("status IN ('OPEN','CANCELLED')", name='ck_volunteer_shift_status'),
                      CheckConstraint("kind IN ('SHELTER','RELIEF','FIELD_SUPPORT')", name='ck_volunteer_shift_kind'),
                      CheckConstraint('version > 0', name='ck_volunteer_shift_version'))
    id = Column(Integer, primary_key=True)
    title = Column(String(160), nullable=False)
    kind = Column(String(20), nullable=False)
    place_id = Column(String(100), nullable=False)
    shelter_id = Column(Integer, ForeignKey('shelters.id'))
    starts_at = Column(DateTime(timezone=True), nullable=False, index=True)
    ends_at = Column(DateTime(timezone=True), nullable=False)
    slots = Column(Integer, nullable=False)
    required_skills = Column(JSON, nullable=False, default=list)
    instructions = Column(String(2000), nullable=False, default='')
    status = Column(String(20), nullable=False, default='OPEN')
    version = Column(Integer, nullable=False, default=1)
    created_by_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=now)
    created_at = Column(DateTime(timezone=True), nullable=False, default=now)


class VolunteerShiftEvent(Base):
    __tablename__ = 'volunteer_shift_events'
    id = Column(Integer, primary_key=True)
    shift_id = Column(Integer, ForeignKey('volunteer_shifts.id'), nullable=False, index=True)
    actor_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    action = Column(String(30), nullable=False)
    version = Column(Integer, nullable=False)
    details = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=now)


class VolunteerSignup(Base):
    __tablename__ = 'volunteer_signups'
    __table_args__ = (UniqueConstraint('shift_id', 'user_id', name='uq_volunteer_signup_shift_user'),
                      CheckConstraint("status IN ('REGISTERED','CANCELLED','CHECKED_IN','COMPLETED','NO_SHOW')", name='ck_volunteer_signup_status'),
                      CheckConstraint('version > 0', name='ck_volunteer_signup_version'))
    id = Column(Integer, primary_key=True)
    shift_id = Column(Integer, ForeignKey('volunteer_shifts.id'), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    application_version = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False, default='REGISTERED')
    version = Column(Integer, nullable=False, default=1)
    note = Column(String(1000), nullable=False, default='')
    created_at = Column(DateTime(timezone=True), nullable=False, default=now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=now)


class VolunteerSignupEvent(Base):
    __tablename__ = 'volunteer_signup_events'
    id = Column(Integer, primary_key=True)
    signup_id = Column(Integer, ForeignKey('volunteer_signups.id'), nullable=False, index=True)
    actor_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    status = Column(String(20), nullable=False)
    version = Column(Integer, nullable=False)
    note = Column(String(1000), nullable=False, default='')
    created_at = Column(DateTime(timezone=True), nullable=False, default=now)
