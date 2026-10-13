from sqlalchemy import Column, Integer, String
from backend.database.connection import Base


class Team(Base):
    __tablename__ = "response_teams"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    team_type = Column(String(50), nullable=False)
    status = Column(String(30), nullable=False, default="AVAILABLE")