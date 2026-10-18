from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from backend.database.connection import get_db
from backend.models import Role, User
from backend.schemas.investigation_schema import (AnalysisUpsert,AnalysisResponse,InvestigationStart,InvestigationUpdate,InvestigationResponse)
from backend.services.investigation_service import (get_analysis,save_analysis,get_investigation,start_investigation,update_investigation)
from backend.utils.permissions import require_roles
router = APIRouter(prefix="/api/admin/incidents",tags=["Week 2 — Investigation"],)
admin_user = require_roles(Role.ADMIN)
@router.get("/{incident_id}/analysis",response_model=AnalysisResponse | None)
def read_analysis(incident_id: int,db: Session = Depends(get_db),_user: User = Depends(admin_user)):
    return get_analysis(db, incident_id)
@router.put("/{incident_id}/analysis",response_model=AnalysisResponse)
def write_analysis(incident_id: int,data: AnalysisUpsert,db: Session = Depends(get_db),user: User = Depends(admin_user)):
    return save_analysis(db,incident_id,user.id,data)
@router.get("/{incident_id}/investigation",response_model=InvestigationResponse | None,)
def read_investigation(incident_id: int,db: Session = Depends(get_db),_user: User = Depends(admin_user),):
    return get_investigation(db, incident_id)
@router.post("/{incident_id}/investigation",response_model=InvestigationResponse,status_code=status.HTTP_201_CREATED)
def begin_investigation(incident_id: int,data: InvestigationStart,db: Session = Depends(get_db),user: User = Depends(admin_user)):
    return start_investigation(db,incident_id,user.id,data.assigned_to_name)
@router.patch("/investigations/{investigation_id}",response_model=InvestigationResponse,)
def revise_investigation(investigation_id: int,data: InvestigationUpdate,db: Session = Depends(get_db),user: User = Depends(admin_user),):
    return update_investigation(db,investigation_id,user.id,data)