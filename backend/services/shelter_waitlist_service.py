"""FIFO fitting-group offers reserve capacity until the citizen accepts or expires.

All capacity writers lock the shelter first. Worker helpers flush but do not
commit; request handlers commit their complete action. Confirmed reservations
and arrivals are never expired by this module.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from backend.models import Role, User
from backend.models.shelter import Shelter
from backend.models.shelter_registration import ShelterRegistration, ShelterRegistrationEvent
from backend.models.shelter_waitlist import ShelterWaitlist, ShelterWaitlistEvent
from backend.services.shelter_service import require_shelter, save_snapshot, shelter_view


ACTIVE = ("WAITING", "OFFERED")


def utc(value=None):
    value = value or datetime.now(timezone.utc)
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def offered_spaces(db, shelter_id):
    return db.scalar(select(func.coalesce(func.sum(ShelterWaitlist.party_size), 0)).where(
        ShelterWaitlist.shelter_id == shelter_id, ShelterWaitlist.status == "OFFERED")) or 0


def _minutes(db, supplied):
    if supplied is None:
        from backend.services.automation_policy_service import get_policy
        supplied = get_policy(db).waitlist_offer_minutes
    if not isinstance(supplied, int) or not 1 <= supplied <= 1440:
        raise ValueError("Waitlist offer duration must be between 1 and 1440 minutes")
    return supplied


def _event(db, row, note, *, actor=None, now=None):
    db.add(ShelterWaitlistEvent(waitlist_id=row.id, status=row.status, version=row.version,
                               actor_id=actor.id if actor is not None else None, note=note,
                               created_at=utc(now)))


def _notify(db, row, title, message):
    from backend.services.automation_notifications import notify_user
    notify_user(db, row.citizen_id, title, message,
                f"shelter-waitlist:{row.id}:{row.status.lower()}:{row.version}",
                f"/shelters/{row.shelter_id}/waitlist")


def _capacity(db, shelter, delta, note, *, actor=None, now=None):
    if not 0 <= shelter.occupied + delta <= shelter.capacity:
        raise HTTPException(409, "Shelter capacity is inconsistent. Ask reception to review its records.")
    shelter.occupied += delta
    if shelter.status != "CLOSED":
        shelter.status = "FULL" if shelter.occupied >= shelter.capacity else "OPEN"
    shelter.version += 1
    shelter.updated_at = utc(now)
    save_snapshot(db, shelter, actor, note)


def process_shelter_waitlist(db, shelter, *, now=None, offer_minutes=None):
    """Caller holds this shelter's row lock. Mutate/flush; do not commit."""
    checked = utc(now)
    duration = _minutes(db, offer_minutes)
    counts = {"offered": 0, "expired": 0, "cancelled": 0}
    rows = list(db.scalars(select(ShelterWaitlist).where(
        ShelterWaitlist.shelter_id == shelter.id, ShelterWaitlist.status.in_(ACTIVE))
        .order_by(ShelterWaitlist.id).with_for_update().execution_options(populate_existing=True)))
    for row in rows:
        citizen = db.get(User, row.citizen_id)
        eligible = citizen is not None and citizen.active and citizen.role == Role.CITIZEN
        if not eligible or (row.status == "OFFERED" and shelter.status == "CLOSED"):
            if row.status == "OFFERED":
                _capacity(db, shelter, -row.party_size, f"Waitlist #{row.id}: automatic offer cancellation; held spaces released", now=checked)
            row.status = "CANCELLED"; row.version += 1; row.updated_at = checked
            row.skip_reason = "Shelter closed" if eligible else "Citizen account no longer eligible"
            _event(db, row, row.skip_reason, now=checked)
            if eligible:
                _notify(db, row, "Shelter offer cancelled", f"{shelter.name} is closed. Your held spaces were released; contact reception before travelling.")
            counts["cancelled"] += 1
        elif row.status == "OFFERED" and (row.offer_expires_at is None or utc(row.offer_expires_at) <= checked):
            _capacity(db, shelter, -row.party_size, f"Waitlist #{row.id}: offer expired; held spaces released", now=checked)
            row.status = "EXPIRED"; row.version += 1; row.updated_at = checked
            _event(db, row, "Offer acceptance deadline passed; only the offer's held spaces were released.", now=checked)
            _notify(db, row, "Shelter offer expired", f"Your offer for {row.party_size} spaces at {shelter.name} expired. You can join the waiting list again.")
            counts["expired"] += 1
    # Keep groups together. An older group that cannot fit retains its place;
    # smaller groups may use spaces that would otherwise remain unused.
    for row in rows:
        if row.status != "WAITING":
            continue
        if shelter.status == "CLOSED":
            row.skip_reason = "Shelter is closed; waiting list paused"
            continue
        existing = db.scalar(select(ShelterRegistration.id).where(
            ShelterRegistration.shelter_id == shelter.id, ShelterRegistration.citizen_id == row.citizen_id,
            ShelterRegistration.status.in_(("RESERVED", "ARRIVED"))))
        if existing is not None:
            row.status = "CANCELLED"; row.version += 1; row.updated_at = checked
            row.skip_reason = "An active shelter registration already exists"
            _event(db, row, row.skip_reason, now=checked)
            counts["cancelled"] += 1
            continue
        if shelter.available_capacity < row.party_size:
            row.skip_reason = f"Waiting for {row.party_size} spaces together; {shelter.available_capacity} currently recorded"
            continue
        if shelter.status != "OPEN":
            row.skip_reason = "Shelter is not open for offers; reception must confirm its status"
            continue
        row.status = "OFFERED"; row.version += 1; row.updated_at = checked
        row.skip_reason = None; row.offered_at = checked
        row.offer_expires_at = checked + timedelta(minutes=duration)
        _capacity(db, shelter, row.party_size, f"Waitlist #{row.id}: {row.party_size} spaces held until explicit offer acceptance or expiry", now=checked)
        _event(db, row, "Spaces held temporarily. Citizen must explicitly accept before the deadline; arrival is not confirmed.", now=checked)
        _notify(db, row, "Shelter spaces offered", f"{shelter.name} can hold {row.party_size} spaces for your group for {duration} minutes. Open your waiting list to accept before the deadline.")
        counts["offered"] += 1
    db.flush()
    return counts


def process_waitlists(db, *, now=None, offer_minutes=15):
    """Durable worker tick. Each shelter is locked in ID order; caller commits."""
    totals = {"offered": 0, "expired": 0, "cancelled": 0}
    ids = list(db.scalars(select(ShelterWaitlist.shelter_id).where(
        ShelterWaitlist.status.in_(ACTIVE)).distinct().order_by(ShelterWaitlist.shelter_id)))
    for shelter_id in ids:
        shelter = require_shelter(db, shelter_id, lock=True)
        counts = process_shelter_waitlist(db, shelter, now=now, offer_minutes=offer_minutes)
        for key, value in counts.items():
            totals[key] += value
    return totals


def _view(db, row, shelter=None):
    citizen = db.get(User, row.citizen_id)
    events = list(db.scalars(select(ShelterWaitlistEvent).where(
        ShelterWaitlistEvent.waitlist_id == row.id).order_by(ShelterWaitlistEvent.version)))
    ahead = db.scalar(select(func.count(ShelterWaitlist.id)).where(
        ShelterWaitlist.shelter_id == row.shelter_id, ShelterWaitlist.status == "WAITING",
        ShelterWaitlist.id < row.id)) if row.status == "WAITING" else None
    return {"id": row.id, "shelter_id": row.shelter_id, "citizen_id": row.citizen_id,
            "citizen": {"full_name": citizen.full_name, "email": citizen.email} if citizen else None,
            "party_size": row.party_size, "origin_district": row.origin_district,
            "origin_locality": row.origin_locality, "origin_latitude": row.origin_latitude,
            "origin_longitude": row.origin_longitude, "contact": row.contact, "note": row.note,
            "status": row.status, "version": row.version, "skip_reason": row.skip_reason,
            "offered_at": row.offered_at, "offer_expires_at": row.offer_expires_at,
            "registration_id": row.registration_id, "groups_ahead": ahead,
            "created_at": row.created_at, "updated_at": row.updated_at,
            "shelter": shelter_view(shelter or require_shelter(db, row.shelter_id)),
            "history": [{"status": event.status, "version": event.version, "actor_id": event.actor_id,
                         "note": event.note, "created_at": event.created_at} for event in events]}


def list_waitlist(db, user, shelter_id=None):
    query = select(ShelterWaitlist)
    shelter = None
    if shelter_id is not None:
        shelter = require_shelter(db, shelter_id)
        query = query.where(ShelterWaitlist.shelter_id == shelter_id)
    if user.role == Role.CITIZEN:
        query = query.where(ShelterWaitlist.citizen_id == user.id)
    elif shelter is None:
        raise HTTPException(403, "Open a shelter you manage to view its private waiting list.")
    else:
        require_shelter(db, shelter_id, user=user)
    return [_view(db, row, shelter) for row in db.scalars(query.order_by(ShelterWaitlist.id.desc()))]


def join(db, user, shelter_id, data):
    if user.role != Role.CITIZEN:
        raise HTTPException(403, "Only citizen accounts can join a shelter waiting list.")
    from backend.services.shelter_registration_service import canonical_district
    shelter = require_shelter(db, shelter_id, lock=True)
    values = data.model_dump(mode="json")
    values["origin_district"] = canonical_district(values["origin_district"])
    fingerprint = hashlib.sha256(json.dumps({"shelter_id": shelter_id, **values}, sort_keys=True,
                                           separators=(",", ":")).encode()).hexdigest()
    old = db.scalar(select(ShelterWaitlist).where(ShelterWaitlist.citizen_id == user.id,
                                                 ShelterWaitlist.request_key == str(data.request_key)))
    if old is not None:
        if old.request_fingerprint != fingerprint:
            raise HTTPException(409, "This waiting-list request was already used with different details. Reload before retrying.")
        return _view(db, old, shelter), False
    process_shelter_waitlist(db, shelter)
    if shelter.status == "CLOSED":
        db.commit()
        raise HTTPException(409, "This shelter is closed and cannot accept waiting-list requests.")
    if db.scalar(select(ShelterRegistration.id).where(ShelterRegistration.shelter_id == shelter_id,
        ShelterRegistration.citizen_id == user.id, ShelterRegistration.status.in_(("RESERVED", "ARRIVED")))) is not None:
        db.commit()
        raise HTTPException(409, "You already have an active registration at this shelter.")
    if db.scalar(select(ShelterWaitlist.id).where(ShelterWaitlist.shelter_id == shelter_id,
        ShelterWaitlist.citizen_id == user.id, ShelterWaitlist.status.in_(ACTIVE))) is not None:
        db.commit()
        raise HTTPException(409, "You already have an active waiting-list entry at this shelter. View it below.")
    row = ShelterWaitlist(shelter_id=shelter_id, citizen_id=user.id, **values,
                          request_fingerprint=fingerprint, status="WAITING", version=1)
    db.add(row)
    try:
        db.flush()
        _event(db, row, "Citizen joined the waiting list; no arrival or registration is confirmed.", actor=user)
        process_shelter_waitlist(db, shelter)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "The waiting list changed while saving. Refresh before retrying.") from None
    return _view(db, row, shelter), True


def _locked_entry(db, user, entry_id, *, allow_staff=False):
    original = db.get(ShelterWaitlist, entry_id)
    if original is None or (user.role == Role.CITIZEN and original.citizen_id != user.id):
        raise HTTPException(404, "Waiting-list entry not found")
    if user.role != Role.CITIZEN and not allow_staff:
        raise HTTPException(403, "Only the citizen can accept their own shelter offer.")
    shelter = require_shelter(db, original.shelter_id,
                             user=None if user.role == Role.CITIZEN else user, lock=True)
    row = db.scalar(select(ShelterWaitlist).where(ShelterWaitlist.id == entry_id)
                    .with_for_update().execution_options(populate_existing=True))
    return row, shelter


def accept(db, user, entry_id, data, *, now=None):
    row, shelter = _locked_entry(db, user, entry_id)
    checked = utc(now)
    if row.status == "ACCEPTED" and data.expected_version in {row.version, row.version - 1}:
        return _view(db, row, shelter)
    # Expiry/closure wins over an old form, and the released space can be offered
    # to the next eligible group in this same serialized transaction.
    process_shelter_waitlist(db, shelter, now=checked)
    if row.status != "OFFERED":
        db.commit()
        raise HTTPException(409, "This offer is no longer available. Refresh your waiting list.")
    if row.version != data.expected_version:
        db.commit()
        raise HTTPException(409, "The waiting-list entry changed. Reload its latest version before accepting.")
    if db.scalar(select(ShelterRegistration.id).where(ShelterRegistration.shelter_id == shelter.id,
        ShelterRegistration.citizen_id == user.id, ShelterRegistration.status.in_(("RESERVED", "ARRIVED")))) is not None:
        raise HTTPException(409, "An active registration already exists for this shelter.")
    values = {key: getattr(row, key) for key in ("party_size", "origin_district", "origin_locality",
              "origin_latitude", "origin_longitude", "contact", "note")}
    registration = ShelterRegistration(shelter_id=shelter.id, citizen_id=user.id, **values,
        request_key=str(uuid4()),
        request_fingerprint=hashlib.sha256(f"waitlist:{row.id}:accepted".encode()).hexdigest(),
        status="RESERVED", version=1, created_at=checked, updated_at=checked)
    db.add(registration); db.flush()
    db.add(ShelterRegistrationEvent(registration_id=registration.id, status="RESERVED", version=1,
        actor_id=user.id, note=f"Citizen accepted waitlist offer #{row.id}; arrival not confirmed.", created_at=checked))
    row.status = "ACCEPTED"; row.version += 1; row.updated_at = checked
    row.registration_id = registration.id
    _event(db, row, "Citizen accepted the held spaces. A reservation was created without increasing the held count again.", actor=user, now=checked)
    _notify(db, row, "Shelter offer accepted", f"Your {row.party_size} spaces at {shelter.name} are now reserved. Contact reception before travelling; arrival is confirmed separately.")
    db.commit()
    return _view(db, row, shelter)


def cancel(db, user, entry_id, data, *, now=None):
    row, shelter = _locked_entry(db, user, entry_id, allow_staff=True)
    checked = utc(now)
    if row.status == "CANCELLED" and data.expected_version in {row.version, row.version - 1}:
        return _view(db, row, shelter)
    process_shelter_waitlist(db, shelter, now=checked)
    if row.status not in ACTIVE or row.version != data.expected_version:
        db.commit()
        raise HTTPException(409, "The waiting-list entry changed or is no longer active. Refresh before cancelling.")
    if row.status == "OFFERED":
        _capacity(db, shelter, -row.party_size, f"Waitlist #{row.id}: offer cancelled; held spaces released", actor=user, now=checked)
    row.status = "CANCELLED"; row.version += 1; row.updated_at = checked
    row.skip_reason = None
    _event(db, row, "Waiting-list entry cancelled; any offer's held spaces were released.", actor=user, now=checked)
    _notify(db, row, "Shelter waiting list cancelled", f"Your waiting-list entry at {shelter.name} was cancelled. Any temporary offer's held spaces were released.")
    process_shelter_waitlist(db, shelter, now=checked)
    db.commit()
    return _view(db, row, shelter)
