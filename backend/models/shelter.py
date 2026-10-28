from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
)

from backend.database.connection import Base


class Shelter(Base):
    __tablename__ = "shelters"

    __table_args__ = (
        CheckConstraint(
            "capacity > 0 AND occupied >= 0 AND occupied <= capacity"
        ),
    )

    id = Column(Integer, primary_key=True)

    name = Column(String(100), nullable=False)

    location = Column(String(255), nullable=False)

    capacity = Column(Integer, nullable=False)

    occupied = Column(
        Integer,
        nullable=False,
        default=0,
    )

    team_id = Column(
        Integer,
        ForeignKey("response_teams.id"),
        nullable=False,
    )

    version = Column(
        Integer,
        nullable=False,
        default=1,
    )


class ShelterUpdate(Base):
    __tablename__ = "shelter_updates"

    id = Column(Integer, primary_key=True)

    shelter_id = Column(
        Integer,
        ForeignKey("shelters.id"),
        nullable=False,
        index=True,
    )

    capacity = Column(Integer, nullable=False)

    occupied = Column(Integer, nullable=False)

    version = Column(Integer, nullable=False)

    note = Column(String(1000), nullable=False)

    changed_by = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False,
    )

    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )