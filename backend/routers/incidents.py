from fastapi import (APIRouter,Depends,Header,HTTPException,status)
from sqlalchemy.orm import Session
from backend.database.connection import get_db
from backend.schemas.incident_schema import (IncidentCreate,IncidentResponse,IncidentHistoryResponse)
from backend.services.incident_service import (create_incident,get_my_incidents,get_incident_by_id,get_incident_history,get_incident_history,assign_incident_team)
from backend.utils.validators import (validate_user_id,validate_incident_owner)
from backend.schemas.team_schema import AssignTeamRequest
router=APIRouter(prefix="/api/incidents",tags=["Incidents"])
def get_current_user_id(x_user_id:int=Header(...)):
    try:
        user_id=validate_user_id(x_user_id)
        return user_id
    except ValueError as e:
        raise HTTPException(status_code=400,detail="Invalid user ID")
@router.post("/",response_model=IncidentResponse,status_code=status.HTTP_201_CREATED)
def create_incident_api(data:IncidentCreate,db:Session=Depends(get_db),user_id:int=Depends(get_current_user_id)):
    incident=create_incident(db=db,user_id=user_id,message=data.message,location=data.location,people_affected=data.people_affected,help_required=data.help_required)
    return incident
@router.get("/",response_model=list[IncidentResponse])
def my_incidents(db:Session=Depends(get_db),user_id:int=Depends(get_current_user_id)):
    return get_my_incidents(db=db,user_id=user_id)
@router.get("/{incident_id}",response_model=IncidentResponse)
def incident_detail(incident_id:int,db:Session=Depends(get_db),user_id:int=Depends(get_current_user_id)):
    incident=get_incident_by_id(db=db,incident_id=incident_id)
    if incident is None:
        raise HTTPException(status_code=404,detail="Incident not found")
    if not validate_incident_owner(incident.user_id,user_id):
        raise HTTPException(status_code=403,detail="You are not allowed to access this incident")
    return incident
@router.get("/{incident_id}/history",response_model=list[IncidentHistoryResponse])
def incident_history(incident_id:int,db:Session=Depends(get_db),user_id:int=Depends(get_current_user_id)):
    incident=get_incident_by_id(db=db,incident_id=incident_id)
    if incident is None:
        raise HTTPException(status_code=404,detail="Incident not found")
    if not validate_incident_owner(incident.user_id,user_id):
        raise HTTPException(status_code=403,detail="You are not allowed to access this incident")
    return get_incident_history(db=db,incident_id=incident_id)
@router.post("/admin/assign-team")
def assign_team_to_incident(
    data: AssignTeamRequest,
    db: Session = Depends(get_db)
):
    incident = assign_incident_team(
        db=db,
        incident_id=data.incident_id,
        team_id=data.team_id,
        assignment_note=data.assignment_note
    )

    if incident is None:
        raise HTTPException(
            status_code=400,
            detail="Incident or available team not found"
        )

    return incident
