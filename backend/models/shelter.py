from datetime import datetime, timezone
from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String
from backend.database.connection import Base


def utc_now():
    return datetime.now(timezone.utc)


class Shelter(Base):
    __tablename__ = "shelters"
    __table_args__ = (
        CheckConstraint("capacity >= 0 AND occupied >= 0 AND occupied <= capacity", name="ck_shelter_counts"),
        CheckConstraint("status IN ('OPEN', 'FULL', 'CLOSED')", name="ck_shelter_status"),
        Index("ix_shelters_district_status", "district", "status"),
    )
    id = Column(Integer, primary_key=True)
    name = Column(String(160), nullable=False)
    district = Column(String(100), index=True)
    locality = Column(String(120), index=True)
    address = Column(String(300))
    location = Column(String(255))
    capacity = Column(Integer, nullable=False)
    occupied = Column(Integer, nullable=False, default=0)
    status = Column(String(10), nullable=False, default="OPEN")
    contact = Column(String(60))
    source_name = Column(String(200))
    team_id = Column(Integer, ForeignKey("response_teams.id"))
    version = Column(Integer, nullable=False, default=1)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    @property
    def available_capacity(self):
        return max(0, self.capacity - self.occupied)


class ShelterUpdate(Base):
    __tablename__ = "shelter_updates"
    id = Column(Integer, primary_key=True)
    shelter_id = Column(Integer, ForeignKey("shelters.id"), nullable=False, index=True)
    capacity = Column(Integer, nullable=False)
    occupied = Column(Integer, nullable=False)
    version = Column(Integer, nullable=False)
    note = Column(String(1000), nullable=False)
    changed_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
