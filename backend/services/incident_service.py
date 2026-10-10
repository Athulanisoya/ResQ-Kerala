from datetime import datetime
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.incident import Incident, IncidentStatusHistory
from backend.models.team import Team


def generate_report_reference(db: Session):
    # Counting rows duplicates references during concurrent submissions/deletion.
    # Keep the original prefix/date while letting the unique constraint protect
    # a random identifier that does not depend on another request's transaction.
    return f"RESQ {datetime.now():%Y%m%d} {uuid4().hex.upper()}"


def create_incident(db: Session, user_id: int, message: str, location: str,
                    people_affected=None, help_required=None, disaster_type="Flood"):
    incident = Incident(
        report_reference=generate_report_reference(db), user_id=user_id,
        message=message, location=location, people_affected=people_affected,
        help_required=help_required, disaster_type=disaster_type, status="SUBMITTED",
    )
    try:
        db.add(incident)
        db.flush()
        db.add(IncidentStatusHistory(
            incident_id=incident.id, status="SUBMITTED", note="Incident report submitted",
        ))
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(incident)
    return incident


def get_my_incidents(db: Session, user_id: int):
    return (db.query(Incident).filter(Incident.user_id == user_id)
            .order_by(Incident.created_at.desc(), Incident.id.desc()).all())


def get_incident_by_id(db: Session, incident_id: int):
    return db.get(Incident, incident_id)


def get_incident_history(db: Session, incident_id: int):
    return (db.query(IncidentStatusHistory)
            .filter(IncidentStatusHistory.incident_id == incident_id)
            .order_by(IncidentStatusHistory.created_at.asc(), IncidentStatusHistory.id.asc()).all())


def review_incident(db: Session, incident_id: int, status: str, note: str | None):
    incident = db.scalar(select(Incident).where(Incident.id == incident_id).with_for_update())
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    allowed = {"SUBMITTED": {"UNDER_REVIEW", "VERIFIED"}, "UNDER_REVIEW": {"VERIFIED"}}
    if status not in allowed.get(incident.status, set()):
        raise HTTPException(status_code=409, detail="This report cannot move to that review status.")
    incident.status = status
    db.add(IncidentStatusHistory(incident_id=incident.id, status=status,
                                note=note or "Admin reviewed the incident report"))
    db.commit()
    db.refresh(incident)
    return incident


def assign_team(db: Session, incident_id: int, team_id: int):
    # Lock the report and selected team so simultaneous admins cannot assign an
    # incident twice or give a busy team two tasks. PostgreSQL enforces the locks.
    incident = db.scalar(select(Incident).where(Incident.id == incident_id).with_for_update())
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    if incident.status != "VERIFIED" or incident.assigned_team_id is not None:
        raise HTTPException(status_code=409, detail="Only a verified, unassigned report can be assigned.")
    team = db.scalar(select(Team).where(Team.id == team_id).with_for_update())
    if team is None:
        raise HTTPException(status_code=404, detail="Response team not found")
    if not team.available:
        raise HTTPException(status_code=409, detail="This response team is already assigned.")
    incident.assigned_team_id = team.id
    incident.status = "ASSIGNED"
    team.available = False
    db.add(IncidentStatusHistory(incident_id=incident.id, status="ASSIGNED",
                                note=f"Admin assigned {team.name}"))
    db.commit()
    db.refresh(incident)
    return incident
