"""Human location confirmations and duplicate links preserve original reports."""
from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, CheckConstraint
from backend.database.connection import Base


class LocationConfirmation(Base):
    __tablename__ = "incident_location_confirmations"
    id = Column(Integer, primary_key=True)
    incident_id = Column(Integer, ForeignKey("incident_reports.id"), nullable=False, index=True)
    confirmed_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    input_hash = Column(String(64), nullable=False)
    place_id = Column(String(100), nullable=False)
    locality = Column(String(255), nullable=True)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class DuplicateLink(Base):
    __tablename__ = "incident_duplicate_links"
    __table_args__ = (
        UniqueConstraint("first_incident_id", "second_incident_id", name="uq_duplicate_report_pair"),
        CheckConstraint("first_incident_id < second_incident_id", name="ck_duplicate_pair_order"),
    )
    id = Column(Integer, primary_key=True)
    first_incident_id = Column(Integer, ForeignKey("incident_reports.id"), nullable=False, index=True)
    second_incident_id = Column(Integer, ForeignKey("incident_reports.id"), nullable=False, index=True)
    confirmed_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
