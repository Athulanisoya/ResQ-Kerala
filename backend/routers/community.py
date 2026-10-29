"""Community news and donations. Pledges are not payment transactions."""
from datetime import datetime
import hashlib
import json
from decimal import Decimal
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session
from backend.database.connection import get_db
from backend.models.user import Role, User
from backend.models.community import CommunityNews, DonationCampaign, DonationPledge, DonationPledgeReceipt
from backend.utils.permissions import get_current_user, require_roles

router = APIRouter(prefix="/api/community", tags=["Community"])

class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

class NewsInput(Input):
    title: str = Field(min_length=3, max_length=160)
    body: str = Field(min_length=5, max_length=10000)
    source: str | None = Field(default=None, max_length=500)

class CampaignInput(Input):
    title: str = Field(min_length=3, max_length=160)
    description: str = Field(min_length=5, max_length=5000)

class PledgeInput(Input):
    kind: Literal["MONEY", "SUPPLIES"]
    description: str = Field(min_length=2, max_length=200)
    quantity: Decimal = Field(gt=0, le=1000000000, max_digits=14, decimal_places=2, allow_inf_nan=False)
    unit: str = Field(min_length=1, max_length=40)
    idempotency_key: str = Field(min_length=16, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    @model_validator(mode="after")
    def require_currency(self):
        if self.kind == "MONEY" and self.unit != "INR":
            raise ValueError("Money pledges must use INR")
        return self

class ReviewInput(Input):
    status: Literal["RECEIVED", "REJECTED"]
    note: str = Field(min_length=3, max_length=1000)

class GeneralPledgeInput(PledgeInput):
    campaign_id: int | None = Field(default=None, gt=0)


def news_view(row):
    return {key: getattr(row, key) for key in ("id", "title", "body", "source", "status", "created_by", "verified_by", "published_by", "created_at", "published_at")}

def campaign_view(row):
    return {key: getattr(row, key) for key in ("id", "title", "description", "status", "created_by", "created_at")}

def pledge_view(row):
    return {key: getattr(row, key) for key in ("id", "campaign_id", "donor_id", "kind", "description", "quantity", "unit", "status", "recorded_by", "review_note", "created_at", "reviewed_at")}

def locked(db, model, item_id):
    row = db.scalar(select(model).where(model.id == item_id).with_for_update())
    if row is None:
        raise HTTPException(404, "Record not found")
    return row

@router.get("/news")
def list_news(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    query = select(CommunityNews)
    if user.role != Role.ADMIN:
        query = query.where(CommunityNews.status == "PUBLISHED")
    return [news_view(row) for row in db.scalars(query.order_by(CommunityNews.id.desc()))]

@router.post("/news", status_code=201)
def create_news(data: NewsInput, db: Session = Depends(get_db), user: User = Depends(require_roles(Role.ADMIN))):
    row = CommunityNews(**data.model_dump(), created_by=user.id, status="DRAFT")
    db.add(row); db.commit(); db.refresh(row)
    return news_view(row)

@router.post("/news/{news_id}/verify")
def verify_news(news_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles(Role.ADMIN))):
    row = locked(db, CommunityNews, news_id)
    if row.status != "DRAFT":
        raise HTTPException(409, "Only draft news can be verified")
    row.status, row.verified_by = "VERIFIED", user.id
    db.commit(); return news_view(row)

@router.post("/news/{news_id}/publish")
def publish_news(news_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles(Role.ADMIN))):
    row = locked(db, CommunityNews, news_id)
    if row.status != "VERIFIED":
        raise HTTPException(409, "Verify this update before publishing")
    row.status, row.published_by, row.published_at = "PUBLISHED", user.id, datetime.utcnow()
    db.commit(); return news_view(row)

@router.get("/campaigns")
def list_campaigns(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    query = select(DonationCampaign)
    if user.role != Role.ADMIN:
        query = query.where(DonationCampaign.status == "ACTIVE")
    return [campaign_view(row) for row in db.scalars(query.order_by(DonationCampaign.id.desc()))]

@router.post("/campaigns", status_code=201)
def create_campaign(data: CampaignInput, db: Session = Depends(get_db), user: User = Depends(require_roles(Role.ADMIN))):
    row = DonationCampaign(**data.model_dump(), created_by=user.id, status="ACTIVE")
    db.add(row); db.commit(); db.refresh(row)
    return campaign_view(row)

@router.post("/campaigns/{campaign_id}/close")
def close_campaign(campaign_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles(Role.ADMIN))):
    row = locked(db, DonationCampaign, campaign_id)
    if row.status != "ACTIVE":
        raise HTTPException(409, "Campaign is already closed")
    row.status = "CLOSED"; db.commit(); return campaign_view(row)

@router.post("/campaigns/{campaign_id}/pledges", status_code=201)
def create_pledge(campaign_id: int | None, data: PledgeInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    # Lock the donor first so retries, including cross-campaign retries, share
    # one ordering and cannot create duplicate records during a race.
    db.scalar(select(User.id).where(User.id == user.id).with_for_update())
    payload = data.model_dump(exclude={"idempotency_key"})
    fingerprint = hashlib.sha256(json.dumps({"campaign_id": campaign_id,
        **{**payload, "quantity": str(data.quantity.normalize())}}, sort_keys=True).encode()).hexdigest()
    prior = db.scalar(select(DonationPledgeReceipt).where(
        DonationPledgeReceipt.donor_id == user.id,
        DonationPledgeReceipt.idempotency_key == data.idempotency_key))
    if prior is not None:
        if prior.fingerprint != fingerprint:
            raise HTTPException(409, "This pledge key was already used for different details")
        return pledge_view(db.get(DonationPledge, prior.pledge_id))
    if campaign_id is not None:
        campaign = locked(db, DonationCampaign, campaign_id)
        if campaign.status != "ACTIVE":
            raise HTTPException(409, "Campaign is closed")
    row = DonationPledge(**payload, campaign_id=campaign_id, donor_id=user.id, status="PENDING")
    db.add(row); db.flush()
    db.add(DonationPledgeReceipt(donor_id=user.id, idempotency_key=data.idempotency_key,
                                 fingerprint=fingerprint, pledge_id=row.id))
    db.commit(); db.refresh(row)
    return pledge_view(row)

@router.post("/pledges", status_code=201)
def add_donation_pledge(data: GeneralPledgeInput, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Record general relief support or a pledge to an active campaign."""
    payload = PledgeInput.model_validate(data.model_dump(exclude={"campaign_id"}))
    return create_pledge(data.campaign_id, payload, db, user)

@router.get("/pledges")
def list_pledges(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    query = select(DonationPledge)
    if user.role != Role.ADMIN:
        query = query.where(DonationPledge.donor_id == user.id)
    return [pledge_view(row) for row in db.scalars(query.order_by(DonationPledge.id.desc()))]

@router.post("/pledges/{pledge_id}/review")
def review_pledge(pledge_id: int, data: ReviewInput, db: Session = Depends(get_db), user: User = Depends(require_roles(Role.ADMIN))):
    row = locked(db, DonationPledge, pledge_id)
    if row.status != "PENDING":
        raise HTTPException(409, "This pledge was already reviewed")
    row.status, row.review_note, row.recorded_by, row.reviewed_at = data.status, data.note, user.id, datetime.utcnow()
    db.commit(); return pledge_view(row)
