from datetime import datetime, timedelta, timezone
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal
from sqlalchemy import select
from backend.models.shelter_facilities import ShelterFacilities, ShelterFacilitiesEvent

LABELS = {'wheelchair_access': 'Wheelchair access', 'accessible_toilets': 'Accessible toilets',
          'medical_support': 'Medical support', 'charging': 'Charging facilities', 'pets_allowed': 'Pets allowed'}
FacilityKey = Literal['wheelchair_access', 'accessible_toilets', 'medical_support', 'charging', 'pets_allowed']
State = Literal['YES', 'NO', 'UNKNOWN']

class FacilitiesInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    expected_version: int = Field(ge=0, strict=True)
    wheelchair_access: State
    accessible_toilets: State
    medical_support: State
    charging: State
    pets_allowed: State
    confirmed: Literal[True]
    note: str = Field(min_length=3, max_length=1000)

def public_view(record):
    stamp = record.confirmed_at if record else None
    if stamp and stamp.tzinfo is None: stamp = stamp.replace(tzinfo=timezone.utc)
    checked = datetime.now(timezone.utc)
    state = 'unknown' if stamp is None or stamp > checked+timedelta(minutes=5) else 'stale' if checked-stamp > timedelta(days=30) else 'current'
    return {'facility_details': {key: getattr(record, key) if record else 'UNKNOWN' for key in LABELS},
            'facility_confirmed_at': stamp.isoformat() if stamp else None, 'facility_freshness': state,
            'facility_version': record.version if record else 0}

def from_shelter(row):
    from sqlalchemy.orm.exc import DetachedInstanceError
    try: return public_view(getattr(row, 'facility_profile', None))
    except DetachedInstanceError: return public_view(None)

def update(db, shelter_id, user, data):
    from backend.services.shelter_service import require_shelter
    require_shelter(db, shelter_id, user=user, lock=True)
    record = db.scalar(select(ShelterFacilities).where(ShelterFacilities.shelter_id == shelter_id).execution_options(populate_existing=True))
    if (record.version if record else 0) != data.expected_version:
        raise HTTPException(409, 'Facility details changed. Reload before confirming them.')
    if record is None:
        record = ShelterFacilities(shelter_id=shelter_id, version=0); db.add(record)
    for key in LABELS: setattr(record, key, getattr(data, key))
    record.version += 1; record.confirmed_by_id = user.id; record.confirmed_at = datetime.now(timezone.utc)
    db.add(ShelterFacilitiesEvent(shelter_id=shelter_id, actor_id=user.id, version=record.version,
        details={key: getattr(record, key) for key in LABELS}, note=data.note))
    db.commit()
    return public_view(record)
