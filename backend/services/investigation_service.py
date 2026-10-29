from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from backend.models.incident import Incident
from backend.models.investigation import (IncidentAnalysis, InvestigationReport, InvestigationTeamAssignment)
from backend.models import Role, Team
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
    incident = require_incident(db,incident_id, lock=True)
    if incident.status in {"CLOSED", "CANCELLED", "REJECTED"}:
        raise HTTPException(status_code=409, detail="A closed incident cannot receive an investigation assignment")
    record=db.scalar(select(InvestigationReport).where(InvestigationReport.incident_id==incident_id).with_for_update())
    if record is None:
         record=InvestigationReport(incident_id=incident_id,assigned_to_name=assigned_to_name,status="IN_PROGRESS",created_by_user_id=user_id,updated_by_user_id=user_id)
         db.add(record)
    else:
        if record.status in {"COMPLETE", "COMPLETED"}:
            raise HTTPException(status_code=409,detail="This investigation is already completed")
        # A free-text reassignment revokes any earlier team identity.
        assignment = db.scalar(select(InvestigationTeamAssignment).where(
            InvestigationTeamAssignment.investigation_id == record.id).with_for_update())
        if assignment is not None:
            db.delete(assignment)
        record.assigned_to_name=assigned_to_name
        record.updated_by_user_id=user_id
        if record.status=="OPEN":
            record.status="IN_PROGRESS"

    db.commit()
    db.refresh(record)
    return record
def update_investigation(db:Session,investigation_id:int,user_id:int,data, *, user=None):
    initial = db.get(InvestigationReport, investigation_id)
    if initial is None:
        if user is not None and user.role != Role.ADMIN:
            raise HTTPException(status_code=403, detail="Only the assigned investigation team can access this investigation")
        raise HTTPException(status_code=404, detail="Investigation not found")
    incident = require_incident(db, initial.incident_id, lock=True)
    record=db.scalar(select(InvestigationReport).where(InvestigationReport.id==investigation_id).with_for_update().execution_options(populate_existing=True))
    if record is None:
        if user is not None and user.role != Role.ADMIN:
            raise HTTPException(status_code=403, detail="Only the assigned investigation team can access this investigation")
        raise HTTPException(status_code=404,detail="Investigation not found")
    if user is not None:
        require_investigation_team(db, record, user)
    if incident.status in {"CLOSED", "CANCELLED", "REJECTED"}:
        raise HTTPException(status_code=409, detail="A closed incident cannot be changed")
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


def require_investigation_team(db: Session, record: InvestigationReport, user):
    if user.role == Role.ADMIN:
        return
    assignment = db.scalar(select(InvestigationTeamAssignment).where(
        InvestigationTeamAssignment.investigation_id == record.id))
    team = db.get(Team, user.team_id) if user.team_id is not None else None
    if (user.role != Role.RESPONSE_TEAM or assignment is None or team is None
            or team.team_type.strip().casefold() != "investigation"
            or assignment.team_id != team.id):
        raise HTTPException(status_code=403, detail="Only the assigned investigation team can access this investigation")


def assign_investigation_team(db: Session, incident_id: int, user, team_id: int):
    incident = require_incident(db, incident_id, lock=True)
    if incident.status in {"CLOSED", "CANCELLED", "REJECTED"}:
        raise HTTPException(status_code=409, detail="A closed incident cannot receive an investigation assignment")
    # Lock the team before checking its availability, in the same transaction
    # that creates the assignment. Management holds this lock while taking a
    # team offline, so neither action can race past the other's check.
    team = db.scalar(select(Team).where(Team.id == team_id).with_for_update().execution_options(populate_existing=True))
    if team is None or team.team_type.strip().casefold() != "investigation":
        raise HTTPException(status_code=409, detail="Select an existing investigation team")
    if team.status == "OFFLINE":
        raise HTTPException(status_code=409, detail="An offline investigation team cannot receive assignments")
    record = db.scalar(select(InvestigationReport).where(
        InvestigationReport.incident_id == incident_id).with_for_update())
    if record is None:
        record = InvestigationReport(incident_id=incident_id, assigned_to_name=team.name,
                                     status="IN_PROGRESS", created_by_user_id=user.id,
                                     updated_by_user_id=user.id)
        db.add(record)
        db.flush()
    elif record.status in {"COMPLETE", "COMPLETED"}:
        raise HTTPException(status_code=409, detail="This investigation is already completed")
    else:
        record.assigned_to_name = team.name
        record.updated_by_user_id = user.id
        record.status = "IN_PROGRESS"
    assignment = db.scalar(select(InvestigationTeamAssignment).where(
        InvestigationTeamAssignment.investigation_id == record.id).with_for_update())
    if assignment is None:
        assignment = InvestigationTeamAssignment(investigation_id=record.id, team_id=team.id,
                                                 assigned_by_user_id=user.id)
        db.add(assignment)
    else:
        assignment.team_id = team.id
        assignment.assigned_by_user_id = user.id
    db.commit()
    db.refresh(record)
    return record


def assigned_investigations(db: Session, user):
    if user.role != Role.RESPONSE_TEAM or user.team_id is None:
        raise HTTPException(status_code=403, detail="Only investigation teams can view assignments")
    team = db.get(Team, user.team_id)
    if team is None or team.team_type.strip().casefold() != "investigation":
        raise HTTPException(status_code=403, detail="Only investigation teams can view assignments")
    from backend.schemas.investigation_schema import InvestigationResponse
    records = db.execute(select(InvestigationReport, Incident).join(
        InvestigationTeamAssignment, InvestigationTeamAssignment.investigation_id == InvestigationReport.id
    ).join(Incident, Incident.id == InvestigationReport.incident_id).where(
        InvestigationTeamAssignment.team_id == team.id).order_by(InvestigationReport.id.desc()))
    return [{**InvestigationResponse.model_validate(record).model_dump(),
             "report_reference": incident.report_reference, "location": incident.location,
             "message": incident.message, "people_affected": incident.people_affected,
             "help_required": incident.help_required} for record, incident in records]
