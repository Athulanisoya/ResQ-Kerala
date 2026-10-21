from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from backend.models.incident import Incident
from backend.models.investigation import (IncidentAnalysis,InvestigationReport)
def require_incident(db:Session,incident_id:int, *, lock=False):
    query = select(Incident).where(Incident.id == incident_id)
    if lock:
        query = query.with_for_update()
    incident=db.scalar(query)
    if incident is None:
        raise HTTPException(status_code=404,detail="Incident not found")
    return incident
def get_analysis(db:Session,incident_id:int):
    require_incident(db,incident_id)
    return db.scalar(select(IncidentAnalysis).where(IncidentAnalysis.incident_id==incident_id))
def save_analysis(db:Session,incident_id:int,user_id:int,data):
    require_incident(db,incident_id, lock=True)
    record=db.scalar(select(IncidentAnalysis).where(IncidentAnalysis.incident_id==incident_id).with_for_update())
    values=data.model_dump()
    if record is None:
        record=IncidentAnalysis(incident_id=incident_id,reviewed_by_user_id=user_id,**values)
        db.add(record)
    else:
        for key,value in values.items():
            setattr(record,key,value)
        record.reviewed_by_user_id=user_id
    db.commit()
    db.refresh(record)
    return record


def save_predicted_severity(db: Session, incident_id: int, user_id: int, severity: str):
    """Change only severity using the latest locked assessment, never a UI snapshot."""
    require_incident(db, incident_id, lock=True)
    record = db.scalar(select(IncidentAnalysis).where(
        IncidentAnalysis.incident_id == incident_id).with_for_update())
    if record is None:
        record = IncidentAnalysis(incident_id=incident_id, severity=severity,
                                  source="AI_MODULE", reviewed_by_user_id=user_id)
        db.add(record)
    else:
        record.severity = severity
        record.source = "AI_MODULE"
        record.reviewed_by_user_id = user_id
    db.commit()
    db.refresh(record)
    return record
def get_investigation(db:Session,incident_id:int):
    require_incident(db,incident_id)
    return db.scalar(select(InvestigationReport).where(InvestigationReport.incident_id==incident_id))
def start_investigation(db:Session,incident_id:int,user_id:int,assigned_to_name:str):
    require_incident(db,incident_id, lock=True)
    record=db.scalar(select(InvestigationReport).where(InvestigationReport.incident_id==incident_id).with_for_update())
    if record is None:
         record=InvestigationReport(incident_id=incident_id,assigned_to_name=assigned_to_name,status="IN_PROGRESS",created_by_user_id=user_id,updated_by_user_id=user_id)
         db.add(record)
    else:
        if record.status in {"COMPLETE", "COMPLETED"}:
            raise HTTPException(status_code=409,detail="This investigation is already completed")
        record.assigned_to_name=assigned_to_name
        record.updated_by_user_id=user_id
        if record.status=="OPEN":
            record.status="IN_PROGRESS"

    db.commit()
    db.refresh(record)
    return record
def update_investigation(db:Session,investigation_id:int,user_id:int,data):
    record=db.scalar(select(InvestigationReport).where(InvestigationReport.id==investigation_id).with_for_update())
    if record is None:
        raise HTTPException(status_code=404,detail="Investigation not found")
    if record.status in {"COMPLETE", "COMPLETED"}:
        raise HTTPException(status_code=409,detail="A completed investigation cannot be edited")
    values=data.model_dump()
    record.status=values["status"]
    record.findings=values["findings"]
    record.action_taken=values["action_taken"]
    record.updated_by_user_id=user_id
    db.commit()
    db.refresh(record)
    return record
