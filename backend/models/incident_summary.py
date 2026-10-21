from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

from backend.database.connection import Base


class IncidentSummary(Base):
    __tablename__ = "incident_summaries"

    id = Column(Integer, primary_key=True)
    incident_id = Column(Integer, ForeignKey("incident_reports.id", ondelete="CASCADE"),
                         nullable=False, unique=True, index=True)
    summary = Column(Text, nullable=False)
    method = Column(String(40), nullable=False)
    input_hash = Column(String(64), nullable=False)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False,
                        default=lambda: datetime.now(timezone.utc))
