from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, JSON, CheckConstraint
from backend.database.connection import Base

class ShelterFacilities(Base):
    __tablename__ = 'shelter_facilities'
    __table_args__ = tuple(CheckConstraint(f"{key} IN ('YES','NO','UNKNOWN')", name='ck_facility_'+key) for key in
        ('wheelchair_access', 'accessible_toilets', 'medical_support', 'charging', 'pets_allowed')) + (CheckConstraint('version > 0', name='ck_facility_version'),)
    shelter_id = Column(Integer, ForeignKey('shelters.id'), primary_key=True)
    wheelchair_access = Column(String(7), nullable=False, default='UNKNOWN')
    accessible_toilets = Column(String(7), nullable=False, default='UNKNOWN')
    medical_support = Column(String(7), nullable=False, default='UNKNOWN')
    charging = Column(String(7), nullable=False, default='UNKNOWN')
    pets_allowed = Column(String(7), nullable=False, default='UNKNOWN')
    confirmed_at = Column(DateTime(timezone=True), nullable=False)
    confirmed_by_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    version = Column(Integer, nullable=False, default=1)

class ShelterFacilitiesEvent(Base):
    __tablename__ = 'shelter_facility_events'
    id = Column(Integer, primary_key=True)
    shelter_id = Column(Integer, ForeignKey('shelters.id'), nullable=False, index=True)
    actor_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    version = Column(Integer, nullable=False)
    details = Column(JSON, nullable=False)
    note = Column(String(1000), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
