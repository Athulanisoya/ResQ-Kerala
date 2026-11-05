"""Capacity-safe reservations; a reservation is not an arrival or a safe route."""
from datetime import datetime, timezone
import hashlib
import json

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from backend.ai.location_extractor import list_places
from backend.models import Role, User
from backend.models.shelter_registration import ShelterRegistration, ShelterRegistrationEvent
from backend.services.shelter_service import require_shelter, save_snapshot, shelter_view


ACTIVE = ("RESERVED", "ARRIVED")


def active_registered_spaces(db, shelter_id):
    return db.scalar(select(func.coalesce(func.sum(ShelterRegistration.party_size), 0)).where(
        ShelterRegistration.shelter_id == shelter_id, ShelterRegistration.status.in_(ACTIVE))) or 0


def districts():
    return sorted((place for place in list_places() if place.kind == "district"), key=lambda place: place.name)


def canonical_district(value):
    normalised = value.casefold()
    matches = [place for place in districts() if normalised in {place.id.casefold(), place.name.casefold(),
                                                              *(alias.casefold() for alias in place.aliases)}]
    if len(matches) != 1:
        raise HTTPException(422, "Select one of Kerala's 14 districts for your current location.")
    return matches[0].name


def _view(db, row, shelter=None):
    citizen = db.get(User, row.citizen_id)
    events = db.scalars(select(ShelterRegistrationEvent).where(
        ShelterRegistrationEvent.registration_id == row.id).order_by(ShelterRegistrationEvent.version)).all()
    return {"id": row.id, "shelter_id": row.shelter_id, "citizen_id": row.citizen_id,
            "citizen": {"id": citizen.id, "full_name": citizen.full_name, "email": citizen.email} if citizen else None,
            "party_size": row.party_size, "origin_district": row.origin_district,
            "origin_locality": row.origin_locality, "origin_latitude": row.origin_latitude,
            "origin_longitude": row.origin_longitude, "contact": row.contact, "note": row.note,
            "status": row.status, "version": row.version, "created_at": row.created_at,
            "updated_at": row.updated_at,
            "shelter": shelter_view(shelter or require_shelter(db, row.shelter_id)),
            "history": [{"status": event.status, "version": event.version, "actor_id": event.actor_id,
                         "note": event.note, "created_at": event.created_at} for event in events]}


def list_registrations(db, user, shelter_id=None):
    query = select(ShelterRegistration)
    shelter = None
    if shelter_id is not None:
        shelter = require_shelter(db, shelter_id)
        query = query.where(ShelterRegistration.shelter_id == shelter_id)
    if user.role == Role.CITIZEN:
        query = query.where(ShelterRegistration.citizen_id == user.id)
    elif shelter is None:
        raise HTTPException(403, "Open a shelter you manage to view its private registrations.")
    else:
        require_shelter(db, shelter_id, user=user)
    return [_view(db, row, shelter) for row in db.scalars(query.order_by(ShelterRegistration.id.desc())).all()]


def _capacity_changed(db, shelter, user, delta, note):
    if shelter.occupied + delta < 0:
        raise HTTPException(409, "Shelter counts are inconsistent. Ask the administrator to review the occupancy record.")
    shelter.occupied += delta
    if shelter.status != "CLOSED":
        shelter.status = "FULL" if shelter.occupied >= shelter.capacity else "OPEN"
    shelter.version += 1
    shelter.updated_at = datetime.now(timezone.utc)
    save_snapshot(db, shelter, user, note)


def reserve(db, user, shelter_id, data):
    if user.role != Role.CITIZEN:
        raise HTTPException(403, "Shelter registration is available to citizen accounts.")
    shelter = require_shelter(db, shelter_id, lock=True)
    values = data.model_dump(mode="json")
    values["origin_district"] = canonical_district(data.origin_district)
    fingerprint = hashlib.sha256(json.dumps({"shelter_id": shelter_id, **values}, sort_keys=True,
                                           separators=(",", ":")).encode()).hexdigest()
    previous = db.scalar(select(ShelterRegistration).where(ShelterRegistration.citizen_id == user.id,
                                                          ShelterRegistration.request_key == str(data.request_key)))
    if previous is not None:
        if previous.request_fingerprint != fingerprint:
            raise HTTPException(409, "This registration request was already used with different details. Reload before making a new request.")
        return _view(db, previous, shelter), False
    if db.scalar(select(ShelterRegistration.id).where(ShelterRegistration.shelter_id == shelter_id,
            ShelterRegistration.citizen_id == user.id, ShelterRegistration.status.in_(ACTIVE))) is not None:
        raise HTTPException(409, "You already have an active registration at this shelter. View it below before making another request.")
    if shelter.status != "OPEN" or shelter.available_capacity < data.party_size:
        raise HTTPException(409, "This shelter cannot reserve that many spaces now. Refresh availability or choose another shelter.")
    row = ShelterRegistration(shelter_id=shelter_id, citizen_id=user.id, **values,
                              request_fingerprint=fingerprint, status="RESERVED", version=1)
    db.add(row)
    try:
        db.flush()
        db.add(ShelterRegistrationEvent(registration_id=row.id, status="RESERVED", version=1,
                                        actor_id=user.id, note="Citizen reserved spaces; arrival not confirmed."))
        _capacity_changed(db, shelter, user, data.party_size, f"Registration #{row.id}: {data.party_size} spaces reserved; arrival not confirmed")
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A registration changed while this request was saving. Refresh before retrying.") from None
    return _view(db, row, shelter), True


def change_status(db, user, registration_id, data):
    # Lock the shelter first for every writer, including the existing capacity editor.
    original = db.get(ShelterRegistration, registration_id)
    if original is None or (user.role == Role.CITIZEN and original.citizen_id != user.id):
        raise HTTPException(404, "Shelter registration not found")
    shelter = require_shelter(db, original.shelter_id, user=None if user.role == Role.CITIZEN else user, lock=True)
    row = db.scalar(select(ShelterRegistration).where(ShelterRegistration.id == registration_id)
                    .with_for_update().execution_options(populate_existing=True))
    if user.role == Role.CITIZEN and data.status != "CANCELLED":
        raise HTTPException(403, "The shelter reception team confirms arrivals and departures.")
    note = data.note or None
    if row.version != data.expected_version:
        latest = db.scalar(select(ShelterRegistrationEvent).where(
            ShelterRegistrationEvent.registration_id == row.id,
            ShelterRegistrationEvent.version == row.version))
        if (row.version == data.expected_version + 1 and row.status == data.status and latest
                and latest.actor_id == user.id and latest.note == note):
            return _view(db, row, shelter)
        raise HTTPException(409, "Registration changed; reload its latest status before updating.")
    allowed = {"RESERVED": {"ARRIVED", "CANCELLED"}, "ARRIVED": {"DEPARTED"}}
    if data.status not in allowed.get(row.status, set()):
        raise HTTPException(409, "That change is not available for the current registration status.")
    if data.status in {"CANCELLED", "DEPARTED"}:
        _capacity_changed(db, shelter, user, -row.party_size,
                          f"Registration #{row.id}: {data.status.lower()}; {row.party_size} spaces released")
    row.status = data.status
    row.version += 1
    row.updated_at = datetime.now(timezone.utc)
    db.add(ShelterRegistrationEvent(registration_id=row.id, status=row.status, version=row.version,
                                    actor_id=user.id, note=note))
    db.commit()
    return _view(db, row, shelter)
