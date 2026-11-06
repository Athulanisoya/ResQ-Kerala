"""Reviewed volunteers and capacity-safe, explicitly joined duty shifts."""
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import case, func, select

from backend.ai.location_extractor import get_place, list_places
from backend.models import Role, Shelter, User
from backend.models.volunteer import (VolunteerApplication, VolunteerApplicationEvent, VolunteerShift,
                                      VolunteerShiftEvent, VolunteerSignup, VolunteerSignupEvent)
from backend.services.automation_notifications import notify_user


SKILLS = {'shelter_support': 'Shelter support', 'food_distribution': 'Food and supply distribution',
          'logistics': 'Logistics', 'translation': 'Translation', 'community_support': 'Community support',
          'trained_first_aid': 'First aid training (declared)'}
KINDS = {'SHELTER': 'Shelter duty', 'RELIEF': 'Relief distribution', 'FIELD_SUPPORT': 'Field support'}
ACTIVE = ('REGISTERED', 'CHECKED_IN')


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def now():
    return datetime.now(timezone.utc)


def _actor(db, actor, role, *, lock=False):
    query = select(User).where(User.id == actor.id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    user = db.scalar(query)
    if user is None or not user.active or user.role != role:
        raise HTTPException(403, 'An active citizen account is required.' if role == Role.CITIZEN else 'Only administrators can manage volunteers.')
    return user


def _version(row, expected, label):
    if (row.version if row else 0) != expected:
        raise HTTPException(409, f'{label} changed. Reload the latest version before trying again.')


def _application(db, user_id, *, lock=False):
    query = select(VolunteerApplication).where(VolunteerApplication.user_id == user_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return db.scalar(query)


def _shift(db, shift_id, *, lock=False):
    query = select(VolunteerShift).where(VolunteerShift.id == shift_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    row = db.scalar(query)
    if row is None:
        raise HTTPException(404, 'Volunteer shift not found')
    return row


def _signup(db, signup_id):
    row = db.get(VolunteerSignup, signup_id)
    if row is None:
        raise HTTPException(404, 'Volunteer signup not found')
    return row


def _locked_signup(db, signup_id):
    return db.scalar(select(VolunteerSignup).where(VolunteerSignup.id == signup_id).with_for_update()
                     .execution_options(populate_existing=True))


def _notify(db, user_id, title, message, key):
    notify_user(db, user_id, title, message, 'volunteer:' + key, '/volunteers')


def catalog():
    return {'places': [place.model_dump(mode='json') for place in list_places()],
            'skills': [{'id': key, 'label': label} for key, label in SKILLS.items()],
            'kinds': [{'id': key, 'label': label} for key, label in KINDS.items()]}


def _place_name(place_id):
    place = get_place(place_id) if place_id else None
    return place.name if place else None


def application_payload(db, row):
    if row is None:
        return None
    user = db.get(User, row.user_id)
    return {name: getattr(row, name) for name in ('id', 'user_id', 'district_id', 'locality_id', 'ward', 'skills',
            'availability', 'status', 'consent_at', 'review_note', 'reviewed_by_id', 'reviewed_at', 'version', 'created_at', 'updated_at')} | {
                'full_name': user.full_name, 'email': user.email, 'account_active': user.active,
                'district': _place_name(row.district_id), 'locality': _place_name(row.locality_id)}


def application_history(db, row):
    return [{'action': event.action, 'version': event.version, 'note': event.note, 'snapshot': event.snapshot,
             'created_at': event.created_at} for event in db.scalars(select(VolunteerApplicationEvent).where(
                 VolunteerApplicationEvent.application_id == row.id).order_by(VolunteerApplicationEvent.id.desc()))]


def my_application(db, actor):
    _actor(db, actor, Role.CITIZEN)
    row = _application(db, actor.id)
    return {'application': application_payload(db, row), 'history': application_history(db, row) if row else []}


def _application_event(db, row, actor, action, note=''):
    db.add(VolunteerApplicationEvent(application_id=row.id, actor_id=actor.id, action=action, version=row.version,
           note=note, snapshot={key: getattr(row, key) for key in ('district_id', 'locality_id', 'ward', 'skills', 'availability', 'status')}))


def _signup_event(db, row, actor, status, note):
    row.status = status
    row.note = note
    row.updated_at = now()
    row.version += 1
    db.add(VolunteerSignupEvent(signup_id=row.id, actor_id=actor.id, status=status, version=row.version, note=note))


def _release_future_signups(db, user_id, actor, reason):
    # All callers already hold this user's row. Join, cancellation and attendance
    # use the same user -> shift -> signup order, including across distinct shifts.
    rows = list(db.scalars(select(VolunteerSignup).join(VolunteerShift, VolunteerSignup.shift_id == VolunteerShift.id)
                          .where(VolunteerSignup.user_id == user_id, VolunteerSignup.status == 'REGISTERED',
                                 VolunteerShift.starts_at > now()).order_by(VolunteerSignup.shift_id)))
    for candidate in rows:
        shift = _shift(db, candidate.shift_id, lock=True)
        row = _locked_signup(db, candidate.id)
        if row.status != 'REGISTERED':
            continue
        _signup_event(db, row, actor, 'CANCELLED', reason)
        _notify(db, user_id, 'Volunteer shift signup cancelled', f'{shift.title}: {reason}', f'signup:{row.id}:v{row.version}')
    return len(rows)


def save_application(db, actor, data):
    _actor(db, actor, Role.CITIZEN, lock=True)
    row = _application(db, actor.id, lock=True)
    _version(row, data.expected_version, 'Volunteer application')
    district = get_place(data.district_id)
    locality = get_place(data.locality_id) if data.locality_id else None
    if not district or district.kind != 'district' or (data.locality_id and (
            not locality or locality.kind != 'locality' or locality.district_id != district.id)):
        raise HTTPException(422, 'Choose a catalog district and a locality in the same district, or leave locality unselected.')
    if row is None:
        row = VolunteerApplication(user_id=actor.id, version=1)
        db.add(row)
    else:
        _release_future_signups(db, actor.id, actor, 'Application revised; administrator approval is required again.')
        row.version += 1
    for name in ('district_id', 'locality_id', 'ward', 'availability'):
        setattr(row, name, getattr(data, name))
    row.skills = sorted(set(data.skills))
    row.status = 'PENDING'
    row.consent_at = row.updated_at = now()
    row.review_note = ''
    row.reviewed_by_id = row.reviewed_at = None
    db.flush()
    _application_event(db, row, actor, 'SUBMITTED', 'Application submitted for administrator review.')
    for admin in db.scalars(select(User).where(User.role == Role.ADMIN, User.active.is_(True))):
        _notify(db, admin.id, 'Volunteer application awaiting review', f'{actor.full_name} submitted a volunteer application.',
                f'application:{row.id}:v{row.version}:submitted')
    db.commit()
    return my_application(db, actor)


def list_applications(db, actor, *, offset=0, limit=100):
    _actor(db, actor, Role.ADMIN)
    total = db.scalar(select(func.count()).select_from(VolunteerApplication))
    rows = db.scalars(select(VolunteerApplication).order_by(VolunteerApplication.updated_at.desc(), VolunteerApplication.id.desc())
                      .offset(offset).limit(limit))
    return {'applications': [application_payload(db, row) | {'history': application_history(db, row)} for row in rows],
            'total': total, 'offset': offset, 'limit': limit}


def review_application(db, actor, application_id, data):
    _actor(db, actor, Role.ADMIN)
    initial = db.get(VolunteerApplication, application_id)
    if initial is None:
        raise HTTPException(404, 'Volunteer application not found')
    target = db.scalar(select(User).where(User.id == initial.user_id).with_for_update().execution_options(populate_existing=True))
    row = _application(db, target.id, lock=True)
    _version(row, data.expected_version, 'Volunteer application')
    if data.decision == 'APPROVED' and (not target.active or target.role != Role.CITIZEN):
        raise HTTPException(409, 'Only an active citizen account can be approved as a volunteer.')
    if data.decision == 'SUSPENDED' and row.status != 'APPROVED':
        raise HTTPException(409, 'Only an approved application can be suspended.')
    if row.status == data.decision:
        raise HTTPException(409, 'This application already has that review status.')
    if data.decision != 'APPROVED':
        _release_future_signups(db, target.id, actor, f'Volunteer approval changed to {data.decision.lower()}: {data.note}')
    row.status = data.decision
    row.review_note = data.note
    row.reviewed_by_id = actor.id
    row.reviewed_at = row.updated_at = now()
    row.version += 1
    _application_event(db, row, actor, 'REVIEWED', data.note)
    _notify(db, target.id, 'Volunteer application reviewed', f'Your application is {row.status.lower()}. {data.note}',
            f'application:{row.id}:v{row.version}:reviewed')
    db.commit()
    return application_payload(db, row) | {'history': application_history(db, row)}


def _shift_values(db, data):
    place = get_place(data.place_id)
    if place is None:
        raise HTTPException(422, 'Choose the shift location from the Kerala place catalog.')
    if utc(data.starts_at) <= now():
        raise HTTPException(422, 'Create or edit a shift before its future start time.')
    if data.shelter_id:
        shelter = db.get(Shelter, data.shelter_id)
        if shelter is None or shelter.status == 'CLOSED':
            raise HTTPException(422, 'Choose an existing open shelter, or leave the shelter unselected.')
        if data.kind != 'SHELTER':
            raise HTTPException(422, 'Only shelter duty can link to a shelter.')
    return {name: getattr(data, name) for name in ('title', 'kind', 'place_id', 'shelter_id', 'slots', 'instructions')} | {
        'starts_at': utc(data.starts_at), 'ends_at': utc(data.ends_at), 'required_skills': sorted(set(data.required_skills))}


def _shift_event(db, row, actor, action, note=''):
    db.add(VolunteerShiftEvent(shift_id=row.id, actor_id=actor.id, action=action, version=row.version,
                              details={'title': row.title, 'status': row.status, 'slots': row.slots,
                                       'starts_at': utc(row.starts_at).isoformat(), 'ends_at': utc(row.ends_at).isoformat(),
                                       'place_id': row.place_id, 'required_skills': row.required_skills, 'note': note}))


def shift_payload(db, row):
    count = db.scalar(select(func.count()).select_from(VolunteerSignup).where(
        VolunteerSignup.shift_id == row.id, VolunteerSignup.status.in_(ACTIVE)))
    shelter = db.get(Shelter, row.shelter_id) if row.shelter_id else None
    place = get_place(row.place_id)
    return {name: getattr(row, name) for name in ('id', 'title', 'kind', 'place_id', 'shelter_id', 'starts_at', 'ends_at',
            'slots', 'required_skills', 'instructions', 'status', 'version', 'updated_at', 'created_at')} | {
        'place_name': place.name if place else row.place_id, 'district': place.district if place else None,
        'shelter_name': shelter.name if shelter else None, 'shelter_open': shelter.status != 'CLOSED' if shelter else None,
        'registered': count, 'available_slots': max(0, row.slots - count), 'has_started': utc(row.starts_at) <= now(),
        'has_ended': utc(row.ends_at) <= now()}


def signup_payload(db, row, *, roster=False):
    shift = db.get(VolunteerShift, row.shift_id)
    result = {name: getattr(row, name) for name in ('id', 'shift_id', 'user_id', 'application_version', 'status', 'version',
                                                   'note', 'created_at', 'updated_at')}
    result.update(shift_title=shift.title, starts_at=shift.starts_at, ends_at=shift.ends_at,
                  events=[{'status': event.status, 'note': event.note, 'created_at': event.created_at, 'version': event.version}
                          for event in db.scalars(select(VolunteerSignupEvent).where(VolunteerSignupEvent.signup_id == row.id)
                                                  .order_by(VolunteerSignupEvent.id.desc()))])
    if roster:
        user = db.get(User, row.user_id)
        app = _application(db, user.id)
        result.update(full_name=user.full_name, email=user.email, account_active=user.active,
                      application_status=app.status if app else None, declared_skills=app.skills if app else [])
    return result


def list_shifts(db, actor, *, offset=0, limit=100):
    if actor.role not in (Role.CITIZEN, Role.ADMIN):
        raise HTTPException(403, 'Volunteer shifts are available to citizen accounts and administrators.')
    total = db.scalar(select(func.count()).select_from(VolunteerShift))
    rows = list(db.scalars(select(VolunteerShift).order_by(case((VolunteerShift.starts_at > now(), 0), else_=1),
                         VolunteerShift.starts_at, VolunteerShift.id).offset(offset).limit(limit)))
    own = list(db.scalars(select(VolunteerSignup).where(VolunteerSignup.user_id == actor.id)
                           .order_by(VolunteerSignup.updated_at.desc()).limit(200))) if actor.role == Role.CITIZEN else []
    return {'shifts': [shift_payload(db, row) for row in rows], 'total': total, 'offset': offset, 'limit': limit,
            'my_signups': [signup_payload(db, row) for row in own]}


def create_shift(db, actor, data):
    _actor(db, actor, Role.ADMIN)
    row = VolunteerShift(**_shift_values(db, data), created_by_id=actor.id, version=1)
    db.add(row)
    db.flush()
    _shift_event(db, row, actor, 'CREATED')
    db.commit()
    return shift_payload(db, row)


def update_shift(db, actor, shift_id, data):
    _actor(db, actor, Role.ADMIN)
    row = _shift(db, shift_id, lock=True)
    _version(row, data.expected_version, 'Volunteer shift')
    if row.status != 'OPEN' or db.scalar(select(VolunteerSignup.id).where(
            VolunteerSignup.shift_id == row.id, VolunteerSignup.status.in_(ACTIVE)).limit(1)):
        raise HTTPException(409, 'Only open shifts without active signups can be edited. Cancel a booked shift and create a replacement.')
    for name, value in _shift_values(db, data).items():
        setattr(row, name, value)
    row.version += 1
    row.updated_at = now()
    _shift_event(db, row, actor, 'UPDATED')
    db.commit()
    return shift_payload(db, row)


def cancel_shift(db, actor, shift_id, data):
    _actor(db, actor, Role.ADMIN)
    row = _shift(db, shift_id, lock=True)
    _version(row, data.expected_version, 'Volunteer shift')
    if row.status == 'CANCELLED' or utc(row.starts_at) <= now():
        raise HTTPException(409, 'Only a future open shift can be cancelled; record attendance for a shift that has started.')
    row.status = 'CANCELLED'
    row.version += 1
    row.updated_at = now()
    for signup in db.scalars(select(VolunteerSignup).where(VolunteerSignup.shift_id == row.id,
                            VolunteerSignup.status == 'REGISTERED').with_for_update().execution_options(populate_existing=True)):
        _signup_event(db, signup, actor, 'CANCELLED', 'Shift cancelled by administrator: ' + data.note)
        _notify(db, signup.user_id, 'Volunteer shift cancelled', f'{row.title}: {data.note}', f'signup:{signup.id}:v{signup.version}')
    _shift_event(db, row, actor, 'CANCELLED', data.note)
    db.commit()
    return shift_payload(db, row)


def join_shift(db, actor, shift_id, data):
    _actor(db, actor, Role.CITIZEN, lock=True)
    app = _application(db, actor.id, lock=True)
    row = _shift(db, shift_id, lock=True)
    _version(row, data.expected_version, 'Volunteer shift')
    signup = db.scalar(select(VolunteerSignup).where(VolunteerSignup.shift_id == row.id, VolunteerSignup.user_id == actor.id)
                       .with_for_update().execution_options(populate_existing=True))
    if signup and signup.status in ACTIVE:
        return signup_payload(db, signup)
    if app is None or app.status != 'APPROVED':
        raise HTTPException(409, 'Administrator approval of your current volunteer application is required before joining a shift.')
    if row.status != 'OPEN' or utc(row.starts_at) <= now():
        raise HTTPException(409, 'This shift is cancelled or has already started.')
    if row.shelter_id and db.get(Shelter, row.shelter_id).status == 'CLOSED':
        raise HTTPException(409, 'The linked shelter is closed. Contact the shift administrator.')
    if not set(row.required_skills).issubset(app.skills):
        raise HTTPException(409, 'Your reviewed application does not include all declared skills required for this shift.')
    overlap = db.scalar(select(VolunteerSignup.id).join(VolunteerShift, VolunteerSignup.shift_id == VolunteerShift.id).where(
        VolunteerSignup.user_id == actor.id, VolunteerSignup.status.in_(ACTIVE), VolunteerShift.status == 'OPEN',
        VolunteerShift.starts_at < row.ends_at, VolunteerShift.ends_at > row.starts_at,
        VolunteerShift.id != row.id).limit(1))
    if overlap:
        raise HTTPException(409, 'You already have an overlapping volunteer shift. Cancel it before joining this one.')
    count = db.scalar(select(func.count()).select_from(VolunteerSignup).where(
        VolunteerSignup.shift_id == row.id, VolunteerSignup.status.in_(ACTIVE)))
    if count >= row.slots:
        raise HTTPException(409, 'This shift has no available places. Refresh the shift list.')
    if signup is None:
        signup = VolunteerSignup(shift_id=row.id, user_id=actor.id, application_version=app.version, version=1, status='REGISTERED')
        db.add(signup)
        db.flush()
        db.add(VolunteerSignupEvent(signup_id=signup.id, actor_id=actor.id, status='REGISTERED', version=1, note='Volunteer joined shift.'))
    else:
        signup.application_version = app.version
        _signup_event(db, signup, actor, 'REGISTERED', 'Volunteer joined shift again.')
    _notify(db, actor.id, 'Volunteer shift confirmed', f'You joined {row.title}. Check the shift instructions before attending.',
            f'signup:{signup.id}:v{signup.version}')
    db.commit()
    return signup_payload(db, signup)


def cancel_signup(db, actor, signup_id, data):
    _actor(db, actor, Role.CITIZEN, lock=True)
    initial = _signup(db, signup_id)
    if initial.user_id != actor.id:
        raise HTTPException(404, 'Volunteer signup not found')
    shift = _shift(db, initial.shift_id, lock=True)
    row = _locked_signup(db, signup_id)
    _version(row, data.expected_version, 'Volunteer signup')
    if row.status != 'REGISTERED' or utc(shift.starts_at) <= now():
        raise HTTPException(409, 'Only a registered signup for a future shift can be cancelled.')
    _signup_event(db, row, actor, 'CANCELLED', data.note)
    _notify(db, actor.id, 'Volunteer signup cancelled', f'{shift.title}: {data.note}', f'signup:{row.id}:v{row.version}')
    db.commit()
    return signup_payload(db, row)


def roster(db, actor, shift_id):
    _actor(db, actor, Role.ADMIN)
    row = _shift(db, shift_id)
    signups = db.scalars(select(VolunteerSignup).where(VolunteerSignup.shift_id == row.id).order_by(VolunteerSignup.created_at))
    return {'shift': shift_payload(db, row), 'signups': [signup_payload(db, signup, roster=True) for signup in signups],
            'history': [{'action': event.action, 'version': event.version, 'details': event.details, 'created_at': event.created_at}
                        for event in db.scalars(select(VolunteerShiftEvent).where(VolunteerShiftEvent.shift_id == row.id)
                                                .order_by(VolunteerShiftEvent.id.desc()))]}


def record_attendance(db, actor, signup_id, data):
    _actor(db, actor, Role.ADMIN)
    initial = _signup(db, signup_id)
    # Attendance and application review acquire the participant row first.
    participant = db.scalar(select(User).where(User.id == initial.user_id).with_for_update().execution_options(populate_existing=True))
    shift = _shift(db, initial.shift_id, lock=True)
    row = _locked_signup(db, signup_id)
    _version(row, data.expected_version, 'Volunteer signup')
    if shift.status != 'OPEN' or utc(shift.starts_at) > now():
        raise HTTPException(409, 'Attendance can only be recorded after an open shift has started.')
    application = _application(db, initial.user_id)
    if data.status == 'CHECKED_IN' and (not participant.active or participant.role != Role.CITIZEN
            or not application or application.status != 'APPROVED'):
        raise HTTPException(409, 'Only an active citizen with current volunteer approval can check in.')
    valid = {'REGISTERED': {'CHECKED_IN', 'NO_SHOW'}, 'CHECKED_IN': {'COMPLETED'}}
    if data.status not in valid.get(row.status, set()):
        raise HTTPException(409, 'Attendance must follow registered → checked in → completed, or registered → no show.')
    if data.status in ('COMPLETED', 'NO_SHOW') and utc(shift.ends_at) > now():
        raise HTTPException(409, 'Complete a shift or record no show only after its scheduled end.')
    _signup_event(db, row, actor, data.status, data.note)
    _notify(db, row.user_id, 'Volunteer attendance updated', f'{shift.title}: {data.status.replace("_", " ").lower()}. {data.note}',
            f'signup:{row.id}:v{row.version}')
    db.commit()
    return signup_payload(db, row, roster=True)
