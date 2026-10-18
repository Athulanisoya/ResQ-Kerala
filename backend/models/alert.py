"""Administrator-authored alerts with explicit geographic coverage and lifetime."""
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.database.connection import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        CheckConstraint("level IN ('YELLOW', 'ORANGE', 'RED')", name="ck_alert_level"),
        CheckConstraint("place_kind IN ('district', 'locality')", name="ck_alert_place_kind"),
        CheckConstraint("expires_at > starts_at", name="ck_alert_valid_window"),
        Index("ix_alerts_active_window", "expired_at", "starts_at", "expires_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(160))
    message: Mapped[str] = mapped_column(Text)
    level: Mapped[str] = mapped_column(String(10))
    # Store catalog identifiers and readable snapshots. User-entered names never
    # become authoritative coverage, and old alerts stay legible if names change.
    place_id: Mapped[str] = mapped_column(String(100), index=True)
    place_name: Mapped[str] = mapped_column(String(160))
    place_kind: Mapped[str] = mapped_column(String(10))
    district_id: Mapped[str] = mapped_column(String(100), index=True)
    district: Mapped[str] = mapped_column(String(100))
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
