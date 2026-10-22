from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, Text

from backend.database.connection import Base


class ReportAnalysis(Base):
    __tablename__ = "report_analysis"

    id = Column(Integer, primary_key=True, index=True)

    incident_id = Column(
        Integer,
        ForeignKey("incident_reports.id"),
        nullable=False,
        index=True,
    )

    summary = Column(Text, nullable=True)

    summary_is_provisional = Column(
        Boolean,
        nullable=False,
        default=True,
    )

    requires_manual_review = Column(
        Boolean,
        nullable=False,
        default=True,
    )
 
    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )