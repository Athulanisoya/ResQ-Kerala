from datetime import datetime, timezone
from sqlalchemy import (CheckConstraint,DateTime,Index,Integer,String,Text)
from sqlalchemy.orm import Mapped, mapped_column
from backend.database.connection import Base
def utc_now():
    return datetime.now(timezone.utc)
class Shelter(Base):
    __tablename__ = "shelters"
    __table_args__ = (
        CheckConstraint("capacity >= 0", name="ck_shelter_capacity"),
        CheckConstraint("occupied >= 0", name="ck_shelter_occupied"),
        CheckConstraint("occupied <= capacity",name="ck_shelter_occupancy_not_over_capacity"),
        CheckConstraint("status IN ('OPEN', 'FULL', 'CLOSED')",name="ck_shelter_status"),
        Index("ix_shelters_district_status", "district", "status")
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    district: Mapped[str] = mapped_column(String(100), index=True)
    locality: Mapped[str] = mapped_column(String(120), index=True)
    address: Mapped[str] = mapped_column(String(300), nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    occupied: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(10), default="OPEN", nullable=False)
    contact: Mapped[str | None] = mapped_column(String(60), nullable=True)
    source_name: Mapped[str] = mapped_column(String(200), default="ResQ demo seed", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    @property
    def available_capacity(self) -> int:
        return max(0, self.capacity - self.occupied)