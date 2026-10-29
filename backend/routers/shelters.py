import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from backend.database.connection import get_db
from backend.models import Role, User
from backend.models.shelter import Shelter, ShelterUpdate
from backend.schemas.shelter_schema import ShelterCreate, ManagedShelterCreate, ShelterPatch
from backend.services import shelter_service as service
from backend.utils.permissions import get_current_user, require_roles

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/shelters", tags=["Shelters"])


@router.get("")
def list_shelters(
    q: str = Query(default="", max_length=160),
    district: str | None = Query(default=None, max_length=100),
    location: str | None = Query(default=None, min_length=2, max_length=255),
    available_only: bool = True,
    limit: int = Query(default=10, ge=1, le=25),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    rows = service.search_shelters(db, query=q, district=district, location=location, available_only=available_only, limit=limit)
    return [service.shelter_view(row) for row in rows]


@router.get("/{shelter_id}")
def shelter_detail(shelter_id: int, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    return service.shelter_view(service.require_shelter(db, shelter_id))


@router.post("", status_code=201)
def add_shelter(data: ShelterCreate | ManagedShelterCreate, db: Session = Depends(get_db), user: User = Depends(require_roles(Role.ADMIN))):
    try:
        if isinstance(data, ManagedShelterCreate):
            return service.create_managed_shelter(db, user, data)
        return service.shelter_view(service.create_shelter(db, data.model_dump()))
    except IntegrityError as exc:
        db.rollback()
        logger.exception("Shelter database integrity error")
        raise HTTPException(status_code=409, detail="Shelter data violates a database constraint.") from exc


@router.patch("/{shelter_id}")
def update(shelter_id: int, data: ShelterPatch, db: Session = Depends(get_db), user: User = Depends(require_roles(Role.ADMIN, Role.RESPONSE_TEAM))):
    return service.update_shelter(db, shelter_id, user, data)


@router.get("/{shelter_id}/history")
def history(shelter_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles(Role.ADMIN, Role.RESPONSE_TEAM))):
    service.require_shelter(db, shelter_id, user=user)
    rows = db.scalars(select(ShelterUpdate).where(ShelterUpdate.shelter_id == shelter_id).order_by(ShelterUpdate.id))
    return [{"id": row.id, "capacity": row.capacity, "occupied": row.occupied, "version": row.version, "note": row.note, "changed_by": row.changed_by, "created_at": row.created_at} for row in rows]
