"""Private followed places and durable, per-user alert delivery state."""
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint

from backend.database.connection import Base


def utc_now():
    return datetime.now(timezone.utc)


class AlertSubscription(Base):
    __tablename__ = "alert_subscriptions"
    __table_args__ = (UniqueConstraint("user_id", "place_id", name="uq_alert_subscription_user_place"),)
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    place_id = Column(String(100), nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


class AlertSubscriptionDelivery(Base):
    __tablename__ = "alert_subscription_deliveries"
    __table_args__ = (UniqueConstraint("user_id", "alert_id", name="uq_alert_subscription_user_alert"),)
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    alert_id = Column(Integer, ForeignKey("alerts.id", ondelete="CASCADE"), nullable=False, index=True)
    active = Column(Boolean, nullable=False, default=False)
    fingerprint = Column(String(64), nullable=False)
    sequence = Column(Integer, nullable=False, default=0)
    matched_places = Column(Text, nullable=False, default="[]")
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
