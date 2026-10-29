from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.ai.agent import analyze_location
from backend.ai.ollama_status import get_ollama_status
from backend.config import get_settings
from backend.database.connection import get_db
from backend.models import Role, User
from backend.schemas.location_analysis_schema import LocationAnalysisRequest, LocationAnalysisResponse
from backend.services.incident_service import get_incident_by_id
from backend.services.location_analysis_service import latest_location_analysis, save_location_analysis
from backend.utils.permissions import require_roles


router = APIRouter(tags=["Location analysis"])


@router.get("/api/agent/status")
async def agent_status(_user: User = Depends(require_roles(Role.ADMIN))):
    return await get_ollama_status(get_settings())


def require_incident(db, incident_id):
    incident = get_incident_by_id(db, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found.")
    return incident


@router.get("/api/incidents/{incident_id}/location-analysis", response_model=LocationAnalysisResponse)
def get_location_analysis(incident_id: int, db: Session = Depends(get_db),
                          _user: User = Depends(require_roles(Role.ADMIN))):
    require_incident(db, incident_id)
    row = latest_location_analysis(db, incident_id)
    if row is None:
        raise HTTPException(status_code=404, detail="This report has no location analysis yet.")
    return row


@router.post("/api/incidents/{incident_id}/location-analysis", response_model=LocationAnalysisResponse)
async def run_location_analysis(incident_id: int, data: LocationAnalysisRequest,
                                db: Session = Depends(get_db), user: User = Depends(require_roles(Role.ADMIN))):
    incident = require_incident(db, incident_id)
    result = await analyze_location(db, incident.message, incident.location, use_agent=data.use_agent)
    try:
        row = save_location_analysis(db, incident, result, user.id)
        db.commit()
        db.refresh(row)
        return row
    except Exception:
        db.rollback()
        raise
