from datetime import datetime, timezone
from sqlalchemy import Column, Integer, ForeignKey, String, Text, JSON, Date, DateTime
from backend.database.connection import Base

class PreparednessPlan(Base):
    __tablename__ = 'household_preparedness_plans'
    user_id = Column(Integer, ForeignKey('users.id'), primary_key=True)
    version = Column(Integer, nullable=False, default=1)
    language = Column(String(2), nullable=False, default='en')
    guidance_revision = Column(String(30), nullable=False)
    completed = Column(JSON, nullable=False, default=list)
    nearby_meeting = Column(String(255), nullable=False, default='')
    outside_meeting = Column(String(255), nullable=False, default='')
    contacts = Column(JSON, nullable=False, default=list)
    support_plan = Column(Text, nullable=False, default='')
    next_review_on = Column(Date)
    reviewed_at = Column(DateTime(timezone=True))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
