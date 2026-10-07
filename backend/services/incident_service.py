from datetime import datetime
from sqlalchemy.orm import Session
from backend.models.incident import (Incident,IncidentStatusHistory)
def generate_report_reference(db:Session):
    count=db.query(Incident).count()+1
    date_part=datetime.now().strftime("%Y%m%d")
    return f"RESQ {date_part} {count:04d}"
def create_incident(db:Session,user_id:int,message:str,location:str,people_affected=None,help_required=None):
    reference=generate_report_reference(db)
    incident=Incident(report_reference=reference,user_id=user_id,message=message,location=location,people_affected=people_affected,help_required=help_required,status="SUBMITTED")
    db.add(incident)
    db.commit()
    db.refresh(incident)
    history=IncidentStatusHistory(incident_id=incident.id,status="SUBMITTED",note="Incident report submitted")
    db.add(history)
    db.commit()
    return incident
def get_my_incidents(db:Session,user_id:int):
    return (db.query(Incident).filter(Incident.user_id==user_id).order_by(Incident.created_at.desc()).all())
def get_incident_by_id(db:Session,incident_id:int):
    return (db.query(Incident).filter(Incident.id==incident_id).first())
def get_incident_history(db:Session,incident_id:int):
    return (db.query(IncidentStatusHistory).filter(IncidentStatusHistory.incident_id==incident_id).order_by(IncidentStatusHistory.created_at.asc()).all())
