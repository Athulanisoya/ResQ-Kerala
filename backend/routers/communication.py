from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.database.connection import get_db
from backend.models import Role, User
from backend.routers.incidents import accessible_incident
from backend.schemas.communication_schema import ClarificationCreate, ClarificationReplyCreate, CloseIncidentRequest
from backend.services.communication_service import (
    ask_clarification, cancel_clarification, close_incident, list_clarifications,
    list_notifications, mark_all_notifications_read, mark_notification_read, reply_to_clarification,
)
from backend.utils.permissions import get_current_user, require_roles


router = APIRouter(prefix="/api/communication", tags=["Citizen updates and clarification"])


@router.get("/notifications")
def notifications(limit: int = Query(default=30, ge=1, le=100),
                  before_id: int | None = Query(default=None, gt=0),
                  db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return list_notifications(db, user.id, limit, before_id)


@router.post("/notifications/read-all")
def read_all(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return mark_all_notifications_read(db, user.id)


@router.post("/notifications/{notification_id}/read")
@router.patch("/notifications/{notification_id}/read")
def read_notification(notification_id: int, db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    return mark_notification_read(db, user.id, notification_id)


@router.get("/incidents/{incident_id}/clarifications")
def clarifications(incident_id: int, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    accessible_incident(db, incident_id, user)
    return list_clarifications(db, incident_id)


@router.post("/incidents/{incident_id}/clarifications", status_code=201)
def request_clarification(incident_id: int, data: ClarificationCreate,
                         db: Session = Depends(get_db), user: User = Depends(require_roles(Role.ADMIN))):
    return ask_clarification(db, incident_id, user, data.question, data.required)


@router.post("/clarifications/{clarification_id}/reply")
def reply(clarification_id: int, data: ClarificationReplyCreate,
          db: Session = Depends(get_db), user: User = Depends(require_roles(Role.CITIZEN))):
    return reply_to_clarification(db, clarification_id, user, data.message)


@router.post("/clarifications/{clarification_id}/cancel")
def cancel(clarification_id: int, db: Session = Depends(get_db),
           user: User = Depends(require_roles(Role.ADMIN))):
    return cancel_clarification(db, clarification_id, user)


@router.post("/incidents/{incident_id}/close")
def close(incident_id: int, data: CloseIncidentRequest, db: Session = Depends(get_db),
          user: User = Depends(require_roles(Role.ADMIN))):
    return close_incident(db, incident_id, user, data.note)
