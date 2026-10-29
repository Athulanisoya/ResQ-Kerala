"""Private media attached to an incident report."""
from datetime import datetime
from sqlalchemy import Column, DateTime, ForeignKey, Integer, LargeBinary, String
from backend.database.connection import Base

class IncidentAttachment(Base):
    __tablename__ = "incident_attachments"
    id = Column(Integer, primary_key=True)
    incident_id = Column(Integer, ForeignKey("incident_reports.id"), nullable=False, index=True)
    uploaded_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    media_type = Column(String(30), nullable=False)
    filename = Column(String(200), nullable=False)
    payload = Column(LargeBinary, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
