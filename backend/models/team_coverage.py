"""Administrator-declared operating areas, separate from team availability."""
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, JSON, String

from backend.database.connection import Base


class TeamOperationalProfile(Base):
    __tablename__ = "team_operational_profiles"
    __table_args__ = (CheckConstraint("version > 0", name="ck_team_operational_profile_version"),)
    team_id = Column(Integer, ForeignKey("response_teams.id"), primary_key=True)
    area_ids = Column(JSON, nullable=False, default=list)
    capabilities = Column(JSON, nullable=False, default=list)
    note = Column(String(500), nullable=False, default="")
    version = Column(Integer, nullable=False, default=1)
    updated_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
