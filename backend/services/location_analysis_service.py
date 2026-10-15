import hashlib
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.ai.agent import local_analysis
from backend.models.location_analysis import LocationAnalysis
from backend.schemas.location_analysis_schema import LocationAnalysisResult


def save_location_analysis(db: Session, incident, result: LocationAnalysisResult, created_by_id: int) -> LocationAnalysis:
    values = result.model_dump(mode="json")
    values["input_hash"] = hashlib.sha256(json.dumps([incident.message, incident.location], ensure_ascii=False).encode()).hexdigest()
    row = LocationAnalysis(incident_id=incident.id, created_by_id=created_by_id, **values)
    db.add(row)
    db.flush()
    return row


def analyze_new_incident(db: Session, incident) -> LocationAnalysis:
    return save_location_analysis(db, incident, local_analysis(db, incident.message, incident.location), incident.user_id)


def latest_location_analysis(db: Session, incident_id: int) -> LocationAnalysis | None:
    return db.scalar(select(LocationAnalysis).where(LocationAnalysis.incident_id == incident_id).order_by(LocationAnalysis.id.desc()).limit(1))
