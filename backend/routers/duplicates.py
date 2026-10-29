"""Admin-only possible-duplicate report review aid; never merges reports."""
from difflib import SequenceMatcher
import re
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from backend.database.connection import get_db
from backend.models.incident import Incident
from backend.models.user import Role, User
from backend.utils.permissions import require_roles

router = APIRouter(prefix='/api/admin/incidents', tags=['Incident review'])

def normalize(text):
    return ' '.join(re.findall(r'\w+', (text or '').casefold()))

@router.get('/{incident_id}/possible-duplicates')
def possible_duplicates(incident_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles(Role.ADMIN))):
    incident = db.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(404, 'Incident not found')
    location = normalize(incident.location)
    message = normalize(incident.message)
    if not location or not message:
        return []
    candidates = db.scalars(select(Incident).where(Incident.id != incident_id).order_by(Incident.created_at.desc()).limit(1000))
    result = []
    for candidate in candidates:
        if normalize(candidate.location) != location:
            continue
        similarity = SequenceMatcher(None, message, normalize(candidate.message), autojunk=False).ratio()
        if similarity >= .65:
            result.append({'id': candidate.id, 'report_reference': candidate.report_reference,
                           'location': candidate.location, 'message': candidate.message,
                           'status': candidate.status, 'similarity': round(similarity, 2)})
    return sorted(result, key=lambda item: item['similarity'], reverse=True)[:20]
