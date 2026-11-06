from datetime import datetime

from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, UniqueConstraint


from backend.database.connection import Base


class Incident(Base):
    __tablename__ = "incident_reports"
    __table_args__ = (UniqueConstraint("user_id", "client_submission_id", name="uq_incident_user_client_submission"),)

    id = Column(Integer, primary_key=True, index=True)

    report_reference = Column(
        "report_refernce", String(50), unique=True, nullable=False, index=True
    )

    user_id = Column(Integer, nullable=False, index=True)

    # A browser-generated UUID makes replay after a lost response safe. Keep
    # the original payload fingerprint immutable even if staff later add reviews.
    client_submission_id = Column(String(36), nullable=True)
    submission_fingerprint = Column(String(64), nullable=True)

    team_id = Column(Integer, ForeignKey("response_teams.id"), nullable=True)

    message = Column(Text, nullable=False)

    location = Column(String(255), nullable=False)

    people_affected = Column(Integer, nullable=True)

    help_required = Column(String(255), nullable=True)

    disaster_type = Column(String(50), nullable=False, default="Flood")

    assigned_team_id = Column(
        Integer, ForeignKey("response_teams.id"), nullable=True, index=True
    )

    status = Column(String(50), nullable=False, default="SUBMITTED")


    created_at = Column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )


class IncidentStatusHistory(Base):
    __tablename__ = "status_history"

    id = Column(Integer, primary_key=True, index=True)

    incident_id = Column(
        Integer, ForeignKey("incident_reports.id"), nullable=False, index=True
    )

    status = Column(String(50), nullable=False)

    note = Column(Text, nullable=True)

    created_at = Column(
        DateTime, default=datetime.utcnow, nullable=False
    )
