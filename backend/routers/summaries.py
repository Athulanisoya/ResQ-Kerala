from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.database.connection import get_db
from backend.models import Role, User
from backend.routers.incidents import accessible_incident
from backend.schemas.summary_schema import SummaryResponse
from backend.services.summary_service import SummaryUnavailable, get_summary, refresh_summary
from backend.utils.permissions import get_current_user, require_roles


router = APIRouter(prefix="/api/incidents", tags=["Report summaries"])


@router.get("/{incident_id}/summary", response_model=SummaryResponse)
def read_summary(incident_id: int, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    accessible_incident(db, incident_id, user)
    record = get_summary(db, incident_id)
    if record is None:
        raise HTTPException(status_code=404, detail="No generated summary is saved for this report")
    return record


@router.post("/{incident_id}/summary", response_model=SummaryResponse)
def generate_summary(incident_id: int, db: Session = Depends(get_db),
                     user: User = Depends(require_roles(Role.ADMIN))):
    try:
        return refresh_summary(db, incident_id, user.id)
    except SummaryUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
