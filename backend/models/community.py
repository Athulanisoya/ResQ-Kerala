"""Verified community updates and a manually reconciled donation ledger."""
from datetime import datetime
from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from backend.database.connection import Base


class CommunityNews(Base):
    __tablename__ = "community_news"
    __table_args__ = (CheckConstraint("status IN ('DRAFT','VERIFIED','PUBLISHED')", name="ck_community_news_status"),)
    id = Column(Integer, primary_key=True)
    title = Column(String(160), nullable=False)
    body = Column(Text, nullable=False)
    source = Column(String(500), nullable=True)
    status = Column(String(12), nullable=False, default="DRAFT")
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    verified_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    published_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    published_at = Column(DateTime, nullable=True)


class DonationCampaign(Base):
    __tablename__ = "donation_campaigns"
    __table_args__ = (CheckConstraint("status IN ('ACTIVE','CLOSED')", name="ck_campaign_status"),)
    id = Column(Integer, primary_key=True)
    title = Column(String(160), nullable=False)
    description = Column(Text, nullable=False)
    status = Column(String(12), nullable=False, default="ACTIVE")
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class DonationPledge(Base):
    __tablename__ = "donation_pledges"
    __table_args__ = (
        CheckConstraint("kind IN ('MONEY','SUPPLIES')", name="ck_donation_kind"),
        CheckConstraint("status IN ('PENDING','RECEIVED','REJECTED')", name="ck_donation_status"),
        CheckConstraint("quantity > 0", name="ck_donation_quantity"),
    )
    id = Column(Integer, primary_key=True)
    campaign_id = Column(Integer, ForeignKey("donation_campaigns.id"), nullable=True, index=True)
    donor_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    kind = Column(String(12), nullable=False)
    description = Column(String(200), nullable=False)
    quantity = Column(Numeric(14, 2), nullable=False)
    unit = Column(String(40), nullable=False)
    status = Column(String(12), nullable=False, default="PENDING")
    recorded_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    review_note = Column(String(1000), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    reviewed_at = Column(DateTime, nullable=True)


class DonationPledgeReceipt(Base):
    """A donor-scoped retry key, separate from legacy pledge rows."""
    __tablename__ = "donation_pledge_receipts"
    __table_args__ = (UniqueConstraint("donor_id", "idempotency_key", name="uq_pledge_donor_key"),)
    id = Column(Integer, primary_key=True)
    donor_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    idempotency_key = Column(String(100), nullable=False)
    fingerprint = Column(String(64), nullable=False)
    pledge_id = Column(Integer, ForeignKey("donation_pledges.id"), nullable=False, unique=True)
