"""Family sharing is controlled by membership, including for administrators."""
from datetime import datetime, timedelta, timezone
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import select, func
from backend.database.connection import get_db
from backend.models import User, Shelter
from backend.models.family_safety import FamilyCircle, FamilyMember, FamilyInvitation, FamilyEvent
from backend.utils.permissions import get_current_user
from backend.services.automation_notifications import notify_user

router = APIRouter(prefix='/api/family-safety', tags=['Private family safety'])

def now(): return datetime.now(timezone.utc)
def utc(value): return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
def fail(): raise HTTPException(404, 'Family circle or invitation not available')

class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
class CircleInput(Input):
    name: str = Field(min_length=2, max_length=100)
class InviteInput(Input):
    email: EmailStr
class VersionInput(Input):
    expected_version: int = Field(ge=1, strict=True)
class CheckinInput(VersionInput):
    status: Literal['UNKNOWN', 'SAFE', 'NEEDS_CONTACT']
    location: str | None = Field(default=None, max_length=255)
    shelter_id: int | None = Field(default=None, gt=0, strict=True)
    consent: Literal[True]

def member(db, circle_id, user, *, lock=False, owner=False):
    query = select(FamilyCircle).where(FamilyCircle.id == circle_id)
    if lock: query = query.with_for_update().execution_options(populate_existing=True)
    circle = db.scalar(query)
    row = db.scalar(select(FamilyMember).where(FamilyMember.circle_id == circle_id, FamilyMember.user_id == user.id)
                    .execution_options(populate_existing=True))
    if not circle or circle.closed_at or not row or row.left_at or (owner and circle.owner_id != user.id): fail()
    return circle, row

def event(db, circle, user, action):
    db.add(FamilyEvent(circle_id=circle.id, actor_id=user.id, action=action))

def notify(db, user_id, circle, title, key):
    # No private check-in, location or shelter details in retained notifications.
    notify_user(db, user_id, title, 'Open Family safety to review the current sharing details.',
                f'family:{circle.id}:{key}', '/family-safety')

def version(row, value):
    if row.version != value: raise HTTPException(409, 'Sharing changed. Reload before trying again.')

def erase(row):
    row.status, row.location, row.shelter_id, row.reported_at = 'UNKNOWN', None, None, None
    row.version += 1

@router.get('/circles')
def circles(db=Depends(get_db), user=Depends(get_current_user)):
    rows = db.execute(select(FamilyCircle, FamilyMember).join(FamilyMember).where(FamilyMember.user_id == user.id,
           FamilyMember.left_at.is_(None), FamilyCircle.closed_at.is_(None)).order_by(FamilyCircle.id)).all()
    invites = db.execute(select(FamilyInvitation, FamilyCircle, User).join(FamilyCircle, FamilyInvitation.circle_id == FamilyCircle.id)
        .join(User, FamilyCircle.owner_id == User.id).where(FamilyInvitation.recipient_id == user.id,
        FamilyInvitation.status == 'PENDING', FamilyInvitation.expires_at > now(), FamilyCircle.closed_at.is_(None))).all()
    return {'circles': [{'id': c.id, 'name': c.name, 'owner': c.owner_id == user.id, 'version': c.version} for c, _ in rows],
            'invitations': [{'id': i.id, 'circle_name': c.name, 'inviter': owner.full_name, 'expires_at': i.expires_at} for i, c, owner in invites]}

@router.post('/circles', status_code=201)
def create(data: CircleInput, db=Depends(get_db), user=Depends(get_current_user)):
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    if db.scalar(select(func.count()).select_from(FamilyCircle).where(FamilyCircle.owner_id == user.id, FamilyCircle.closed_at.is_(None))) >= 5:
        raise HTTPException(409, 'You can own up to five active circles.')
    circle = FamilyCircle(owner_id=user.id, name=data.name)
    db.add(circle); db.flush()
    db.add(FamilyMember(circle_id=circle.id, user_id=user.id))
    event(db, circle, user, 'CREATED'); db.commit()
    return {'id': circle.id, 'name': circle.name, 'version': circle.version}

@router.get('/circles/{circle_id}')
def detail(circle_id: int, db=Depends(get_db), user=Depends(get_current_user)):
    circle, viewer = member(db, circle_id, user)
    members = []
    for row, person in db.execute(select(FamilyMember, User).join(User, FamilyMember.user_id == User.id).where(
            FamilyMember.circle_id == circle_id, FamilyMember.left_at.is_(None), User.active.is_(True))):
        # Sharing predating this viewer's consent to join isn't inherited.
        visible = row.reported_at and (row.user_id == user.id or utc(row.reported_at) >= utc(viewer.joined_at))
        fresh = bool(visible and now() - utc(row.reported_at) < timedelta(hours=24))
        shelter = db.get(Shelter, row.shelter_id) if fresh and row.shelter_id else None
        members.append({'id': row.id, 'name': person.full_name, 'self': row.user_id == user.id,
            'owner': row.user_id == circle.owner_id, 'version': row.version,
            'status': row.status if fresh else 'UNKNOWN', 'stale': bool(visible and not fresh),
            'reported_at': row.reported_at if visible else None, 'location': row.location if fresh else None,
            'shelter_id': row.shelter_id if fresh else None, 'shelter_name': shelter.name if shelter else None})
    invitations = []
    if circle.owner_id == user.id:
        invitations = [{'id': i.id, 'email': i.email, 'status': 'EXPIRED' if i.status == 'PENDING' and utc(i.expires_at) <= now() else i.status,
                        'expires_at': i.expires_at} for i in db.scalars(select(FamilyInvitation).where(FamilyInvitation.circle_id == circle_id).order_by(FamilyInvitation.id.desc()).limit(100))]
    return {'id': circle.id, 'name': circle.name, 'version': circle.version, 'owner': circle.owner_id == user.id,
            'members': members, 'invitations': invitations}

@router.post('/circles/{circle_id}/invitations', status_code=202)
def invite(circle_id: int, data: InviteInput, db=Depends(get_db), user=Depends(get_current_user)):
    circle, _ = member(db, circle_id, user, lock=True, owner=True)
    if db.scalar(select(func.count()).select_from(FamilyInvitation).where(FamilyInvitation.circle_id == circle_id,
            FamilyInvitation.created_at > now()-timedelta(days=1))) >= 20:
        raise HTTPException(429, 'Up to twenty invitation requests are allowed per circle each day.')
    email = str(data.email).casefold()
    recipient = db.scalar(select(User).where(func.lower(User.email) == email, User.active.is_(True)))
    record = FamilyInvitation(circle_id=circle_id, email=email, recipient_id=recipient.id if recipient else None, expires_at=now()+timedelta(days=7))
    db.add(record); db.flush(); event(db, circle, user, 'INVITATION_REQUESTED')
    if recipient: notify(db, recipient.id, circle, 'Private family circle invitation', f'invite:{record.id}')
    db.commit()
    return {'message': 'Invitation requested. An eligible existing account can review it in Family safety. No email is sent.'}

@router.post('/invitations/{invitation_id}/{decision}')
def decide(invitation_id: int, decision: Literal['accept', 'decline'], db=Depends(get_db), user=Depends(get_current_user)):
    initial = db.get(FamilyInvitation, invitation_id)
    if not initial or initial.recipient_id != user.id: fail()
    circle = db.scalar(select(FamilyCircle).where(FamilyCircle.id == initial.circle_id).with_for_update().execution_options(populate_existing=True))
    record = db.scalar(select(FamilyInvitation).where(FamilyInvitation.id == invitation_id).execution_options(populate_existing=True))
    if circle.closed_at or record.status != 'PENDING' or utc(record.expires_at) <= now(): fail()
    if decision == 'accept':
        if db.scalar(select(func.count()).select_from(FamilyMember).where(FamilyMember.circle_id == circle.id, FamilyMember.left_at.is_(None))) >= 20:
            raise HTTPException(409, 'This circle has reached its twenty-member limit.')
        row = db.scalar(select(FamilyMember).where(FamilyMember.circle_id == circle.id, FamilyMember.user_id == user.id))
        if row and row.left_at is None:
            raise HTTPException(409, 'You already belong to this circle.')
        if row:
            erase(row); row.joined_at, row.left_at = now(), None
        else: db.add(FamilyMember(circle_id=circle.id, user_id=user.id))
    record.status, record.decided_at = ('ACCEPTED' if decision == 'accept' else 'DECLINED'), now()
    event(db, circle, user, 'INVITATION_'+record.status); db.commit()
    return {'circle_id': circle.id, 'status': record.status}

@router.post('/circles/{circle_id}/invitations/{invitation_id}/revoke')
def revoke(circle_id: int, invitation_id: int, db=Depends(get_db), user=Depends(get_current_user)):
    circle, _ = member(db, circle_id, user, lock=True, owner=True)
    record = db.get(FamilyInvitation, invitation_id)
    if not record or record.circle_id != circle_id or record.status != 'PENDING': fail()
    record.status, record.decided_at = 'REVOKED', now()
    event(db, circle, user, 'INVITATION_REVOKED'); db.commit()
    return {'status': 'REVOKED'}

@router.put('/circles/{circle_id}/checkin')
def checkin(circle_id: int, data: CheckinInput, db=Depends(get_db), user=Depends(get_current_user)):
    circle, row = member(db, circle_id, user, lock=True)
    version(row, data.expected_version)
    if data.shelter_id and not db.get(Shelter, data.shelter_id): raise HTTPException(422, 'Choose a recorded shelter or leave it blank.')
    row.status, row.reported_at = data.status, now()
    row.location, row.shelter_id = (data.location or None, data.shelter_id) if data.status != 'UNKNOWN' else (None, None)
    row.version += 1; event(db, circle, user, 'CHECKIN_SHARED'); db.commit()
    return detail(circle_id, db, user)

@router.post('/circles/{circle_id}/withdraw')
def withdraw(circle_id: int, data: VersionInput, db=Depends(get_db), user=Depends(get_current_user)):
    circle, row = member(db, circle_id, user, lock=True); version(row, data.expected_version)
    erase(row); event(db, circle, user, 'CHECKIN_WITHDRAWN'); db.commit()
    return {'status': 'UNKNOWN', 'version': row.version}

@router.post('/circles/{circle_id}/leave')
def leave(circle_id: int, data: VersionInput, db=Depends(get_db), user=Depends(get_current_user)):
    circle, row = member(db, circle_id, user, lock=True); version(row, data.expected_version)
    if circle.owner_id == user.id: raise HTTPException(409, 'The owner must close the circle to end sharing for everyone.')
    erase(row); row.left_at = now(); event(db, circle, user, 'MEMBER_LEFT'); db.commit()
    return {'status': 'LEFT'}

@router.post('/circles/{circle_id}/members/{member_id}/remove')
def remove(circle_id: int, member_id: int, data: VersionInput, db=Depends(get_db), user=Depends(get_current_user)):
    circle, _ = member(db, circle_id, user, lock=True, owner=True)
    row = db.get(FamilyMember, member_id)
    if not row or row.circle_id != circle_id or row.left_at or row.user_id == circle.owner_id: fail()
    version(row, data.expected_version); erase(row); row.left_at = now()
    event(db, circle, user, 'MEMBER_REMOVED'); db.commit()
    return {'status': 'REMOVED'}

@router.post('/circles/{circle_id}/close')
def close(circle_id: int, data: VersionInput, db=Depends(get_db), user=Depends(get_current_user)):
    circle, _ = member(db, circle_id, user, lock=True, owner=True); version(circle, data.expected_version)
    circle.closed_at, circle.version = now(), circle.version+1
    for row in db.scalars(select(FamilyMember).where(FamilyMember.circle_id == circle_id)):
        erase(row); row.left_at = now()
    for record in db.scalars(select(FamilyInvitation).where(FamilyInvitation.circle_id == circle_id, FamilyInvitation.status == 'PENDING')):
        record.status = 'REVOKED'; record.decided_at = now()
    event(db, circle, user, 'CLOSED'); db.commit()
    return {'status': 'CLOSED'}
