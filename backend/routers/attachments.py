"""Bounded incident image and voice uploads with incident-scoped authorization."""
import base64
from pathlib import PurePath
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from backend.database.connection import get_db
from backend.models.attachments import IncidentAttachment
from backend.models.user import Role, User
from backend.models.team import Team
from backend.models.investigation import InvestigationReport, InvestigationTeamAssignment
from backend.utils.permissions import get_current_user, require_incident_access

router = APIRouter(prefix="/api/incidents", tags=["Incident attachments"])
MAX_BYTES = 3 * 1024 * 1024
MAX_FILES = 5

def media_type(data):
    if data.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if data.startswith(b'RIFF') and data[8:12] == b'WEBP':
        return 'image/webp'
    if data.startswith(b'RIFF') and data[8:12] == b'WAVE':
        return 'audio/wav'
    if data.startswith(b'OggS'):
        return 'audio/ogg'
    if data.startswith(b'\x1a\x45\xdf\xa3'):
        return 'audio/webm'
    return None

def require_attachment_access(db, incident_id, user, *, lock=False):
    """Allow the report's owner, assigned response team, admin or investigator.

    The investigator exception is scoped to attachments; it does not grant
    access to unrelated incident endpoints or another team's investigations.
    """
    try:
        return require_incident_access(db, incident_id, user, lock=lock)
    except HTTPException as error:
        if error.status_code != 403 or user.role != Role.RESPONSE_TEAM or not user.team_id:
            raise
        team = db.get(Team, user.team_id)
        if team is None or team.team_type.strip().casefold() != 'investigation':
            raise
        assigned = db.scalar(select(InvestigationTeamAssignment.id).join(
            InvestigationReport, InvestigationTeamAssignment.investigation_id == InvestigationReport.id
        ).where(InvestigationReport.incident_id == incident_id,
                InvestigationTeamAssignment.team_id == user.team_id))
        if assigned is None:
            raise
        # Read-only access; the upload endpoint separately requires the citizen owner.
        from backend.models.incident import Incident
        return db.get(Incident, incident_id)

def metadata(row):
    return {"id": row.id, "incident_id": row.incident_id, "filename": row.filename,
            "media_type": row.media_type, "created_at": row.created_at}

@router.post('/{incident_id}/attachments', status_code=201)
async def upload(incident_id: int, file: UploadFile = File(...), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    incident = require_attachment_access(db, incident_id, user, lock=True)
    if user.role != Role.CITIZEN or incident.user_id != user.id:
        raise HTTPException(403, 'Only the report owner can add media')
    if incident.status in {'CLOSED', 'REJECTED', 'CANCELLED'}:
        raise HTTPException(409, 'Attachments cannot be added to a closed report')
    count = db.scalar(select(func.count()).select_from(IncidentAttachment).where(IncidentAttachment.incident_id == incident_id))
    if count >= MAX_FILES:
        raise HTTPException(409, 'The report already has five attachments')
    data = await file.read(MAX_BYTES + 1)
    if not data or len(data) > MAX_BYTES:
        raise HTTPException(422, 'Attachment must be between 1 byte and 3 MiB')
    kind = media_type(data)
    if not kind:
        raise HTTPException(422, 'Use a JPEG, PNG, WebP, WAV, Ogg or WebM file')
    # Strip both Windows and POSIX path components and avoid control characters.
    name = (file.filename or 'attachment').replace('\\', '/').rsplit('/', 1)[-1]
    name = ''.join(c for c in name if c.isprintable())[:200] or 'attachment'
    row = IncidentAttachment(incident_id=incident_id, uploaded_by=user.id, filename=name, media_type=kind, payload=data)
    db.add(row); db.commit(); db.refresh(row)
    return metadata(row)

@router.get('/{incident_id}/attachments')
def list_attachments(incident_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_attachment_access(db, incident_id, user)
    return [metadata(row) for row in db.scalars(select(IncidentAttachment).where(IncidentAttachment.incident_id == incident_id).order_by(IncidentAttachment.id))]

@router.get('/{incident_id}/attachments/{attachment_id}')
def get_attachment(incident_id: int, attachment_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    require_attachment_access(db, incident_id, user)
    row = db.scalar(select(IncidentAttachment).where(IncidentAttachment.id == attachment_id, IncidentAttachment.incident_id == incident_id))
    if row is None:
        raise HTTPException(404, 'Attachment not found')
    return {**metadata(row), 'base64': base64.b64encode(row.payload).decode('ascii')}
