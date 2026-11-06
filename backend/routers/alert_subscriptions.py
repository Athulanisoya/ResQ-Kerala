"""Private area follows for existing in-app notifications."""
from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from backend.database.connection import get_db
from backend.models.user import User
from backend.services import alert_subscription_service as service
from backend.utils.permissions import get_current_user


router = APIRouter(prefix="/api/alert-subscriptions", tags=["Alert subscriptions"])


class SubscriptionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    place_id: str = Field(min_length=1, max_length=100)


@router.get("")
def followed_areas(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return service.list_subscriptions(db, user)


@router.post("", status_code=201)
def follow(data: SubscriptionCreate, response: Response, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row, created = service.subscribe(db, user, data.place_id)
    response.status_code = 201 if created else 200
    return row


@router.post("/{subscription_id}/unsubscribe")
def unfollow(subscription_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return service.unsubscribe(db, user, subscription_id)
