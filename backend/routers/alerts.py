from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.ai.location_extractor import Place, extract_location, list_places
from backend.database.connection import get_db
from backend.models import Role, User
from backend.schemas.alert_schema import AlertCreate, AlertMatch, AlertMatchRequest, AlertResponse, AlertUpdate
from backend.services.alert_service import create_alert, expire_alert, list_alerts, match_alerts, update_alert
from backend.utils.permissions import get_current_user, require_roles


router = APIRouter(prefix="/api/alerts", tags=["Alerts"])


@router.get("", response_model=list[AlertResponse])
@router.get("/", response_model=list[AlertResponse], include_in_schema=False)
def alerts_api(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if include_inactive and user.role != Role.ADMIN:
        raise HTTPException(status_code=403, detail="Only administrators can view scheduled and expired alerts.")
    return list_alerts(db, include_inactive=include_inactive)


@router.get("/places", response_model=list[Place])
def alert_places(_user: User = Depends(get_current_user)):
    return list_places()


@router.post("/match", response_model=AlertMatch)
def alert_match_api(
    data: AlertMatchRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    return match_alerts(db, extract_location(data.message, data.reported_location))


@router.post("", response_model=AlertResponse, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=AlertResponse, status_code=status.HTTP_201_CREATED, include_in_schema=False)
def create_alert_api(
    data: AlertCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(Role.ADMIN)),
):
    return create_alert(db, data, user.id)


@router.patch("/{alert_id}", response_model=AlertResponse)
def update_alert_api(
    alert_id: int,
    data: AlertUpdate,
    db: Session = Depends(get_db),
    _user: User = Depends(require_roles(Role.ADMIN)),
):
    return update_alert(db, alert_id, data)


@router.post("/{alert_id}/expire", response_model=AlertResponse)
def expire_alert_api(
    alert_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(require_roles(Role.ADMIN)),
):
    return expire_alert(db, alert_id)
