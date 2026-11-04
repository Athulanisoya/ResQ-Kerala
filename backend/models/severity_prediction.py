"""Immutable classifier suggestions and explicit administrator decisions."""
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint

from backend.database.connection import Base


class SeverityPrediction(Base):
    __tablename__ = "severity_predictions"

    id = Column(Integer, primary_key=True)
    incident_id = Column(Integer, ForeignKey("incident_reports.id", ondelete="CASCADE"), nullable=False, index=True)
    predicted_severity = Column(String(20), nullable=False)
    model_version = Column(String(100), nullable=False)
    input_hash = Column(String(64), nullable=False)
    requested_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class SeverityPredictionDecision(Base):
    __tablename__ = "severity_prediction_decisions"
    __table_args__ = (UniqueConstraint("prediction_id", name="uq_severity_prediction_decision"),)

    id = Column(Integer, primary_key=True)
    prediction_id = Column(Integer, ForeignKey("severity_predictions.id", ondelete="CASCADE"), nullable=False, index=True)
    action = Column(String(20), nullable=False)
    reviewed_severity = Column(String(20), nullable=True)
    reviewed_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    reviewed_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    note = Column(Text, nullable=True)
    previous_assessment = Column(JSON, nullable=True)
