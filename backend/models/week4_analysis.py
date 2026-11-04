"""Persisted provisional analysis revisions, never an operational decision."""
from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
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


class Week4SuggestionReview(Base):
    """Append-only decisions about a specific suggestion in a saved revision."""
    __tablename__ = 'week4_suggestion_reviews'
    __table_args__ = (UniqueConstraint('revision_id', 'suggestion_key', 'previous_review_id', name='uq_week4_review_predecessor'),)
    id = Column(Integer, primary_key=True)
    revision_id = Column(Integer, ForeignKey('week4_analysis_revisions.id', ondelete='CASCADE'), nullable=False, index=True)
    suggestion_key = Column(String(50), nullable=False)
    previous_review_id = Column(Integer, nullable=False, default=0)
    decision = Column(String(12), nullable=False)
    original_value = Column(JSON, nullable=True)
    reviewed_value = Column(JSON, nullable=True)
    note = Column(Text, nullable=True)
    reviewed_by = Column(Integer, ForeignKey('users.id'), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
