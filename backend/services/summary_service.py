from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.ai.report_summarizer import METHOD, input_hash, summarize_report
from backend.models.incident import Incident
from backend.models.incident_summary import IncidentSummary


class SummaryUnavailable(RuntimeError):
    pass


def get_summary(db: Session, incident_id: int) -> IncidentSummary | None:
    return db.scalar(select(IncidentSummary).where(IncidentSummary.incident_id == incident_id))


def save_summary(db: Session, incident: Incident, created_by_id: int) -> IncidentSummary:
    """Upsert a draft inside the caller's transaction; never commit here."""
    record = get_summary(db, incident.id)
    values = {
        "summary": summarize_report(incident), "method": METHOD,
        "input_hash": input_hash(incident), "created_by_id": created_by_id,
        "created_at": datetime.now(timezone.utc),
    }
    if record is None:
        record = IncidentSummary(incident_id=incident.id, **values)
        db.add(record)
    else:
        for name, value in values.items():
            setattr(record, name, value)
    db.flush()
    return record


def refresh_summary(db: Session, incident_id: int, created_by_id: int) -> IncidentSummary:
    try:
        # Lock the parent, including for old reports with no draft row yet, so
        # simultaneous refreshes cannot insert two drafts for one incident.
        incident = db.scalar(select(Incident).where(Incident.id == incident_id).with_for_update())
        if incident is None:
            raise HTTPException(status_code=404, detail="Incident not found")
        record = save_summary(db, incident, created_by_id)
        db.commit()
        db.refresh(record)
        return record
    except HTTPException:
        db.rollback()
        raise
    except Exception as error:
        db.rollback()
        raise SummaryUnavailable("The report summary could not be saved. Please try again.") from error
