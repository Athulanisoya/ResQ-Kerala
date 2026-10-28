from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)

from backend.database.connection import Base

class ReliefRequest(Base):
    __tablename__ = "relief_requests"

    __table_args__ = (
        UniqueConstraint(
            "incident_id",
            "item",
            name="uq_relief_incident_item",
        ),
        CheckConstraint(
            "quantity > 0 AND fulfilled >= 0 AND fulfilled <= quantity"
        ),
    )

    id = Column(Integer, primary_key=True)

    incident_id = Column(
        Integer,
        ForeignKey("incident_reports.id"),
        nullable=False,
        index=True,
    )

    item = Column(String(20), nullable=False)
    quantity = Column(Integer, nullable=False)

    fulfilled = Column(
        Integer,
        nullable=False,
        default=0,
    )

    created_by = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False,
    )

    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )

class Inventory(Base):
    __tablename__ = "relief_inventory"

    __table_args__ = (
        CheckConstraint("quantity >= 0"),
    )

    id = Column(Integer, primary_key=True)

    item = Column(String(20), nullable=False, unique=True,)

    quantity = Column(Integer, nullable=False, default=0,)

class Distribution(Base):
    __tablename__ = "relief_distributions"

    __table_args__ = (
        CheckConstraint("quantity > 0"),
    )

    id = Column(Integer, primary_key=True)

    request_id = Column(
        Integer,
        ForeignKey("relief_requests.id"),
        nullable=False,
        index=True,
    )

    inventory_id = Column(
        Integer,
        ForeignKey("relief_inventory.id"),
        nullable=False,
    )

    team_id = Column(
        Integer,
        ForeignKey("response_teams.id"),
        nullable=False,
    )

    recorded_by = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False,
    )

    quantity = Column(Integer, nullable=False)

    idempotency_key = Column(
        String(36),
        nullable=False,
        unique=True,
    )

    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )
