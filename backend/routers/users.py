from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session
from datetime import datetime

from ..database.connection import get_db
from ..models import User
from ..schemas.auth import UserResponse
from ..utils.permissions import get_current_user
from ..services.notification_service import (
    get_user_notifications,
    mark_notification_as_read,
    mark_all_notifications_as_read,
)


router = APIRouter(prefix="/api/users", tags=["Users"])


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    incident_id: int | None
    notification_type: str
    message: str
    is_read: bool
    created_at: datetime


@router.get("/me", response_model=UserResponse)
def me(user: User = Depends(get_current_user)):
    return user


@router.get("/notifications", response_model=list[NotificationResponse])
def list_notifications(
    unread_only: bool = Query(default=False),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return get_user_notifications(
        db=db,
        user_id=user.id,
        unread_only=unread_only,
    )


@router.patch(
    "/notifications/{notification_id}/read",
    response_model=NotificationResponse,
)
def read_notification(
    notification_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    notification = mark_notification_as_read(
        db=db,
        notification_id=notification_id,
        user_id=user.id,
    )

    if notification is None:
        raise HTTPException(
            status_code=404,
            detail="Notification not found",
        )

    return notification


@router.patch("/notifications/read-all")
def read_all_notifications(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    updated_count = mark_all_notifications_as_read(
        db=db,
        user_id=user.id,
    )

    return {
        "message": "Notifications marked as read",
        "updated_count": updated_count,
    }