"""Append-only geography checks; original citizen reports remain unchanged."""
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text

from backend.database.connection import Base


class LocationAnalysis(Base):
    __tablename__ = "location_analyses"
    id = Column(Integer, primary_key=True)
    incident_id = Column(Integer, ForeignKey("incident_reports.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    input_hash = Column(String(64), nullable=False)
    mode = Column(String(20), nullable=False)
    model = Column(String(100), nullable=True)
    extraction = Column(JSON, nullable=False)
    alert_match = Column(JSON, nullable=False)
    tool_calls = Column(JSON, nullable=False, default=list)
    warning = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
