from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.database.connection import get_db
from backend.models import Role, User
from backend.models.shelter import Shelter, ShelterUpdate

from backend.schemas.shelter_schema import (
    ShelterCreate,
    ShelterPatch,
)

from backend.services import shelter_service as service

from backend.utils.permissions import (
    get_current_user,
    require_roles,
)


router = APIRouter(
    prefix="/api/shelters",
    tags=["Week 3 - Shelters"],
)


@router.get("")
def shelters(
    location: str | None = Query(
        default=None,
        min_length=2,
        max_length=255,
    ),
    available_only: bool = False,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    query = select(Shelter)

    if location:
        query = query.where(
            Shelter.location.icontains(
                location,
                autoescape=True,
            )
        )

    if available_only:
        query = query.where(
            Shelter.occupied < Shelter.capacity
        )

    rows = db.scalars(
        query.order_by(Shelter.id)
    )

    return [
        service.shelter_view(row)
        for row in rows
    ]


@router.get("/{shelter_id}")
def detail(
    shelter_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    row = service.require_shelter(
        db,
        shelter_id,
    )

    return service.shelter_view(row)


@router.post("", status_code=201)
def create(
    data: ShelterCreate,
    db: Session = Depends(get_db),
    user: User = Depends(
        require_roles(Role.ADMIN)
    ),
):
    return service.create_shelter(
        db,
        user,
        data,
    )


@router.patch("/{shelter_id}")
def update(
    shelter_id: int,
    data: ShelterPatch,
    db: Session = Depends(get_db),
    user: User = Depends(
        require_roles(
            Role.ADMIN,
            Role.RESPONSE_TEAM,
        )
    ),
):
    return service.update_shelter(
        db,
        shelter_id,
        user,
        data,
    )


@router.get("/{shelter_id}/history")
def history(
    shelter_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(
        require_roles(
            Role.ADMIN,
            Role.RESPONSE_TEAM,
        )
    ),
):
    service.require_shelter(
        db,
        shelter_id,
        user=user,
    )

    rows = db.scalars(
        select(ShelterUpdate)
        .where(ShelterUpdate.shelter_id == shelter_id)
        .order_by(ShelterUpdate.id)
    )

    return [
        {
            "id": row.id,
            "capacity": row.capacity,
            "occupied": row.occupied,
            "version": row.version,
            "note": row.note,
            "changed_by": row.changed_by,
            "created_at": row.created_at,
        }
        for row in rows
    ]