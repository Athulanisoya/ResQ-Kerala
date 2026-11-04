"""Human location clarification and admin-reviewed missing-fact drafts."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from backend.database.connection import get_db
from backend.models import Role, User
from backend.models.incident import Incident
from backend.models.review_assistance import LocationConfirmation
from backend.routers.incidents import accessible_incident
from backend.ai.location_extractor import get_place
from backend.services.review_assistance import (location_follow_up, clarification_suggestions, report_input_hash, confirmed_analysis)
from backend.services.location_analysis_service import save_location_analysis
from backend.utils.permissions import get_current_user, require_roles

router = APIRouter(tags=["Evidence and location review"])


class LocationConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    place_id: str = Field(min_length=1, max_length=100)
    input_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    locality: str | None = Field(default=None, max_length=255)
    note: str | None = Field(default=None, max_length=1000)


@router.get("/api/incidents/{incident_id}/location-clarification")
def get_location_follow_up(incident_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    incident = accessible_incident(db, incident_id, user)
    return location_follow_up(db, incident)


@router.post("/api/incidents/{incident_id}/location-confirmations", status_code=201)
def confirm_location(incident_id: int, data: LocationConfirmRequest, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    incident = accessible_incident(db, incident_id, user)
    if user.role != Role.ADMIN and not (user.role == Role.CITIZEN and incident.user_id == user.id):
        raise HTTPException(403, "Only the reporter or an administrator may confirm the location.")
    db.scalar(select(Incident.id).where(Incident.id == incident_id).with_for_update())
    if data.input_hash != report_input_hash(incident):
        raise HTTPException(409, "The report changed. Reload its location suggestions before confirming.")
    place = get_place(data.place_id)
    if not place:
        raise HTTPException(422, "Choose a place or district from the gazetteer.")
    row = LocationConfirmation(incident_id=incident_id, confirmed_by=user.id, input_hash=data.input_hash,
        place_id=place.id, locality=place.name if place.kind == "locality" else data.locality or None, note=data.note or None)
    db.add(row)
    db.flush()
    # A human confirmation produces a new sourced alert check; the original
    # report and every previous analysis remain intact.
    save_location_analysis(db, incident, confirmed_analysis(db, incident), user.id)
    db.commit()
    return location_follow_up(db, incident)


@router.get("/api/communication/incidents/{incident_id}/clarification-suggestions")
def get_clarification_suggestions(incident_id: int, db: Session = Depends(get_db),
                                  user: User = Depends(require_roles(Role.ADMIN))):
    incident = accessible_incident(db, incident_id, user)
    return {"method": "local_missing_fact_rules", "requires_review": True,
            "suggestions": clarification_suggestions(db, incident)}
