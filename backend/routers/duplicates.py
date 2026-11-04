"""Admin-only possible-duplicate report review aid; never merges reports."""
from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, or_
from sqlalchemy.orm import Session
from backend.database.connection import get_db
from backend.models.incident import Incident
from backend.models.user import Role, User
from backend.utils.permissions import require_roles
from backend.models.review_assistance import DuplicateLink
from backend.services.duplicate_service import compare_reports, DEFAULT_WINDOW_HOURS, confirmed_locations, comparison_input_hash

router = APIRouter(prefix='/api/admin/incidents', tags=['Incident review'])

def require_incident(db, incident_id):
    incident = db.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(404, 'Incident not found')
    return incident


def linked_reports(db, incident_id):
    rows = db.scalars(select(DuplicateLink).where(or_(DuplicateLink.first_incident_id == incident_id,
                                                    DuplicateLink.second_incident_id == incident_id)))
    return {(r.second_incident_id if r.first_incident_id == incident_id else r.first_incident_id): r for r in rows}


def find_candidates(db, incident):
    window = timedelta(hours=DEFAULT_WINDOW_HOURS)
    # Search the complete time window, rather than the latest N global rows.
    candidates = db.scalars(select(Incident).where(Incident.id != incident.id,
        Incident.created_at >= incident.created_at - window,
        Incident.created_at <= incident.created_at + window).execution_options(yield_per=200))
    links = linked_reports(db, incident.id)
    confirmations = confirmed_locations(db, start=incident.created_at - window, end=incident.created_at + window)
    result = []
    for candidate in candidates:
        match = compare_reports(incident, candidate, first_confirmation=confirmations.get(incident.id),
                                second_confirmation=confirmations.get(candidate.id))
        if match:
            link = links.get(candidate.id)
            match['link'] = {'confirmed_by': link.confirmed_by, 'created_at': link.created_at} if link else None
            result.append(match)
    return sorted(result, key=lambda item: (-item['similarity'], item['time_gap_hours'], item['id']))[:20]

@router.get('/{incident_id}/possible-duplicates')
def possible_duplicates(incident_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles(Role.ADMIN))):
    return find_candidates(db, require_incident(db, incident_id))


class DuplicateLinkRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    candidate_id: int = Field(gt=0)
    source_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    candidate_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    note: str | None = Field(default=None, max_length=1000)


@router.get('/{incident_id}/duplicate-links')
def duplicate_links(incident_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles(Role.ADMIN))):
    require_incident(db, incident_id)
    return [{'id': row.id, 'incident_id': other_id, 'confirmed_by': row.confirmed_by,
             'created_at': row.created_at, 'note': row.note} for other_id, row in linked_reports(db, incident_id).items()]


@router.post('/{incident_id}/duplicate-links', status_code=201)
def confirm_duplicate_link(incident_id: int, data: DuplicateLinkRequest, db: Session = Depends(get_db),
                            user: User = Depends(require_roles(Role.ADMIN))):
    if data.candidate_id == incident_id:
        raise HTTPException(422, 'Choose a different report.')
    first_id, second_id = sorted([incident_id, data.candidate_id])
    # Consistent pair lock order serializes competing confirmations on PostgreSQL.
    list(db.scalars(select(Incident.id).where(Incident.id.in_([first_id, second_id])).order_by(Incident.id).with_for_update()))
    incident, candidate = require_incident(db, incident_id), require_incident(db, data.candidate_id)
    confirmations = confirmed_locations(db, incident_ids=[incident_id, data.candidate_id])
    first_confirmation, second_confirmation = confirmations.get(incident_id), confirmations.get(data.candidate_id)
    if (comparison_input_hash(incident, first_confirmation) != data.source_hash
            or comparison_input_hash(candidate, second_confirmation) != data.candidate_hash):
        raise HTTPException(409, 'A report or location confirmation changed. Reload the comparison before linking.')
    if compare_reports(incident, candidate, first_confirmation=first_confirmation, second_confirmation=second_confirmation) is None:
        raise HTTPException(422, 'This pair is outside the matching criteria. Review the reports individually.')
    existing = db.scalar(select(DuplicateLink).where(DuplicateLink.first_incident_id == first_id,
                                                   DuplicateLink.second_incident_id == second_id))
    if existing:
        return {'id': existing.id, 'confirmed_by': existing.confirmed_by, 'created_at': existing.created_at}
    row = DuplicateLink(first_incident_id=first_id, second_incident_id=second_id,
                        confirmed_by=user.id, note=data.note or None)
    db.add(row)
    db.commit()
    db.refresh(row)
    return {'id': row.id, 'confirmed_by': row.confirmed_by, 'created_at': row.created_at}
