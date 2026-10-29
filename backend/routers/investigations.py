from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from backend.database.connection import get_db
from backend.models import Role, User
from backend.schemas.investigation_schema import (AnalysisUpsert,AnalysisResponse,InvestigationStart,InvestigationUpdate,InvestigationResponse,InvestigationTeamAssign,InvestigationAssignmentResponse)
from backend.services.investigation_service import (get_analysis,save_analysis,get_investigation,start_investigation,update_investigation,assign_investigation_team,assigned_investigations,require_investigation_team)
from backend.utils.permissions import require_roles
from backend.models.investigation import InvestigationReport
from fastapi import HTTPException
router = APIRouter(prefix="/api/admin/incidents",tags=["Week 2 — Investigation"],)
admin_user = require_roles(Role.ADMIN)
@router.get("/{incident_id}/analysis",response_model=AnalysisResponse | None)
def read_analysis(incident_id: int,db: Session = Depends(get_db),_user: User = Depends(admin_user)):
    return get_analysis(db, incident_id)
@router.put("/{incident_id}/analysis",response_model=AnalysisResponse)
def write_analysis(incident_id: int,data: AnalysisUpsert,db: Session = Depends(get_db),user: User = Depends(admin_user)):
    return save_analysis(db,incident_id,user.id,data)
@router.get("/{incident_id}/investigation",response_model=InvestigationResponse | None,)
def read_investigation(incident_id: int,db: Session = Depends(get_db),user: User = Depends(require_roles(Role.ADMIN, Role.RESPONSE_TEAM)),):
    record = get_investigation(db, incident_id)
    if record is not None:
        require_investigation_team(db, record, user)
    elif user.role != Role.ADMIN:
        raise HTTPException(status_code=403, detail="No investigation is assigned to your team")
    return record
@router.post("/{incident_id}/investigation",response_model=InvestigationResponse,status_code=status.HTTP_201_CREATED)
def begin_investigation(incident_id: int,data: InvestigationStart,db: Session = Depends(get_db),user: User = Depends(admin_user)):
    return start_investigation(db,incident_id,user.id,data.assigned_to_name)
@router.patch("/investigations/{investigation_id}",response_model=InvestigationResponse,)
def revise_investigation(investigation_id: int,data: InvestigationUpdate,db: Session = Depends(get_db),user: User = Depends(require_roles(Role.ADMIN, Role.RESPONSE_TEAM)),):
    return update_investigation(db,investigation_id,user.id,data,user=user)

@router.post("/{incident_id}/investigation/team", response_model=InvestigationResponse)
def assign_team(incident_id: int, data: InvestigationTeamAssign, db: Session = Depends(get_db), user: User = Depends(admin_user)):
    return assign_investigation_team(db, incident_id, user, data.team_id)

@router.get("/investigations/assigned", response_model=list[InvestigationAssignmentResponse])
def team_assignments(db: Session = Depends(get_db), user: User = Depends(require_roles(Role.RESPONSE_TEAM))):
    return assigned_investigations(db, user)