"""Persisted provisional analysis revisions, never an operational decision."""
from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, UniqueConstraint
from backend.database.connection import Base

class Week4AnalysisRevision(Base):
    __tablename__ = 'week4_analysis_revisions'
    __table_args__ = (UniqueConstraint('incident_id', 'revision', name='uq_week4_incident_revision'),)
    id = Column(Integer, primary_key=True)
    incident_id = Column(Integer, ForeignKey('incident_reports.id'), nullable=False, index=True)
    revision = Column(Integer, nullable=False)
    created_by = Column(Integer, ForeignKey('users.id'), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    result = Column(JSON, nullable=False)
