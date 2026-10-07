from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.database.connection import get_db
from backend.models.incident import Incident
from backend.schemas.incident_schema import IncidentCreate, IncidentResponse, IncidentStatusUpdate

router = APIRouter(
    prefix="/api/incidents",
    tags=["Incidents"]
)

# CRAETE INCIDENT
@router.post("/",response_model=IncidentResponse)
def create_incident(
    incident: IncidentCreate,
    db: Session = Depends(get_db)
):
    new_incident = Incident(
        message=incident.message,
        location=incident.location,
        disaster_type=incident.disaster_type,
        people_affected=incident.people_affected,
        help_required=incident.help_required,
        status="Submitted"
        )

    db.add(new_incident)
    db.commit()
    db.refresh(new_incident)

    return new_incident

# GET ALL INCIDENTS
@router.get("/my",response_model=list[IncidentResponse])
def get_my_incidents(
    db: Session = Depends(get_db)
):
    incidents = db.query(Incident).all()
    return incidents

# GET INCIDENT BY ID
@router.get("/{incident_id}",response_model=IncidentResponse)
def get_incident(
    incident_id: int,
    db:Session = Depends(get_db)
):
    incident= db.query(Incident).filter(
        Incident.id == incident_id
    ).first()

    if incident is None:
        raise HTTPException(
            status_code = 404,
            detail = "Incident not found"
        )


    return incident

# GET INCIDENT STATUS
@router.get("/{incident_id}/status")
def get_incident_status(
   incident_id: int,
   db: Session = Depends(get_db) 
):
    incident = db.query(Incident).filter(
        Incident.id == incident_id
    ).first()

    if incident is None:
        raise HTTPException(
            status_code=404,
            detail="Incident not found"
        )
    return{
        "incident_id": incident.id,
        "status": incident.status
    }

@router.patch("/{incident_id}/status",response_model=IncidentResponse)
def update_incident_status(
    incident_id: int,
    status_update: IncidentStatusUpdate,
    db: Session = Depends(get_db)
):
    incident = db.query(Incident).filter(
        Incident.id == incident_id
    ).first()

    if incident is None:
        raise HTTPException(
            status_code=404,
            detail="Incident not found"
        )
    incident.status = status_update.status

    db.commit()
    db.refresh(incident)
    return incident