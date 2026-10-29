"""Auditable administrative changes without deleting account history."""
from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from backend.database.connection import Base

class AdminChange(Base):
    __tablename__ = "admin_changes"
    id = Column(Integer, primary_key=True)
    actor_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    target_kind = Column(String(20), nullable=False)
    target_id = Column(Integer, nullable=False)
    action = Column(String(40), nullable=False)
    details = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
