"""Consent-based circles; no public directory or location history."""
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, UniqueConstraint, CheckConstraint
from backend.database.connection import Base

def now():
    return datetime.now(timezone.utc)

class FamilyCircle(Base):
    __tablename__ = 'family_circles'
    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime(timezone=True), nullable=False, default=now)
    closed_at = Column(DateTime(timezone=True))

class FamilyMember(Base):
    __tablename__ = 'family_circle_members'
    __table_args__ = (UniqueConstraint('circle_id', 'user_id', name='uq_family_member'),
                      CheckConstraint("status IN ('UNKNOWN','SAFE','NEEDS_CONTACT')", name='ck_family_checkin_status'))
    id = Column(Integer, primary_key=True)
    circle_id = Column(Integer, ForeignKey('family_circles.id'), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    joined_at = Column(DateTime(timezone=True), nullable=False, default=now)
    left_at = Column(DateTime(timezone=True))
    status = Column(String(20), nullable=False, default='UNKNOWN')
    reported_at = Column(DateTime(timezone=True))
    location = Column(String(255))
    shelter_id = Column(Integer, ForeignKey('shelters.id'))
    version = Column(Integer, nullable=False, default=1)

class FamilyInvitation(Base):
    __tablename__ = 'family_circle_invitations'
    id = Column(Integer, primary_key=True)
    circle_id = Column(Integer, ForeignKey('family_circles.id'), nullable=False, index=True)
    email = Column(String(254), nullable=False)
    recipient_id = Column(Integer, ForeignKey('users.id'), index=True)
    status = Column(String(20), nullable=False, default='PENDING')
    created_at = Column(DateTime(timezone=True), nullable=False, default=now)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    decided_at = Column(DateTime(timezone=True))

class FamilyEvent(Base):
    __tablename__ = 'family_circle_events'
    id = Column(Integer, primary_key=True)
    circle_id = Column(Integer, ForeignKey('family_circles.id'), nullable=False, index=True)
    actor_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    action = Column(String(40), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=now)
