from sqlalchemy import Column, Integer, String, Text, DateTime
from datetime import datetime

from backend.database.connection import Base


class Incident(Base):

    __tablename__ = "incident_reports"

    id = Column(Integer, primary_key=True, index=True)

    message = Column(Text, nullable=False)

    location = Column(String(200), nullable=False)

    disaster_type = Column(
        String(50),
        default="Flood"
    )

    people_affected = Column(
        Integer,
        nullable=True
    )

    help_required = Column(
        String(100),
        nullable=True
    )

    status = Column(
        String(50),
        default="Submitted"
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )