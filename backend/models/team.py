"""The small team record needed for Week 1 manual assignment."""
from sqlalchemy import Boolean, Column, Integer, String

from ..database.connection import Base


class Team(Base):
    __tablename__ = "teams"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False, unique=True)
    team_type = Column(String(50), nullable=False, default="Rescue")
    available = Column(Boolean, nullable=False, default=True)
