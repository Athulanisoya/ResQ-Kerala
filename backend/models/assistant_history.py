"""Private assistant conversations; messages are never shared across users."""
from datetime import datetime
from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text
from backend.database.connection import Base

class AssistantSession(Base):
    __tablename__ = 'assistant_sessions'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    title = Column(String(160), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

class AssistantMessage(Base):
    __tablename__ = 'assistant_messages'
    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey('assistant_sessions.id', ondelete='CASCADE'), nullable=False, index=True)
    role = Column(String(12), nullable=False)
    content = Column(Text, nullable=False)
    details = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
