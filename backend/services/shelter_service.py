from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from backend.models.shelter import Shelter
def search_shelters(db: Session,query: str = "",district: str | None = None,available_only: bool = True,limit: int | None = 10,location: str | None = None):
    statement = select(Shelter)
    query = (query or "").strip()
    district = (district or "").strip()
    if query:
        pattern = f"%{query}%"
        statement = statement.where(or_(
                Shelter.name.ilike(pattern),
                Shelter.district.ilike(pattern),
                Shelter.locality.ilike(pattern),
                Shelter.address.ilike(pattern),
                Shelter.location.ilike(pattern),
            )
        )

    if district:
        statement = statement.where(
            Shelter.district.ilike(f"%{district}%")
        )
    if location:
        statement = statement.where(or_(
            Shelter.location.icontains(location, autoescape=True),
            Shelter.district.icontains(location, autoescape=True),
            Shelter.locality.icontains(location, autoescape=True),
            Shelter.address.icontains(location, autoescape=True),
        ))
    if available_only:
        statement = statement.where(
            Shelter.status == "OPEN",
            Shelter.occupied < Shelter.capacity
        )

    statement = statement.order_by(Shelter.district, Shelter.locality, Shelter.name)
    if limit is not None:
        statement = statement.limit(max(1, min(limit, 25)))

    return list(db.scalars(statement).all())
def get_shelter(db: Session, shelter_id: int):
    return db.get(Shelter, shelter_id)
def create_shelter(db: Session, values: dict, user=None):
    shelter = Shelter(**values)
    db.add(shelter)
    db.flush()
    if user is not None:
        save_snapshot(db, shelter, user, "Shelter created")
    db.commit()
    db.refresh(shelter)
    return shelter

from fastapi import HTTPException
from sqlalchemy import select

from backend.models import Role, Team
from backend.models.shelter import Shelter, ShelterUpdate


def shelter_view(row):
    return {
        "id": row.id,
        "name": row.name,
        "location": row.location,
        "district": row.district,
        "locality": row.locality,
        "address": row.address,
        "status": row.status,
        "contact": row.contact,
        "source_name": row.source_name,
        "updated_at": row.updated_at,
        "available_capacity": row.available_capacity,
        "team_id": row.team_id,
        "capacity": row.capacity,
        "occupied": row.occupied,
        "available": row.capacity - row.occupied,
        "version": row.version,
    }


def require_shelter(
    db,
    shelter_id,
    user=None,
    lock=False,
):
    query = select(Shelter).where(
        Shelter.id == shelter_id
    )

    if lock:
        query = query.with_for_update()

    row = db.scalar(query)

    if row is None:
        raise HTTPException(
            404,
            "Shelter not found",
        )

    if user is not None and user.role != Role.ADMIN:
        team = (
            db.get(Team, user.team_id)
            if user.team_id is not None
            else None
        )

        if (
            user.role != Role.RESPONSE_TEAM
            or team is None
            or team.team_type.casefold() != "shelter"
            or row.team_id != team.id
        ):
            raise HTTPException(
                403,
                "Only the designated shelter team can change this shelter",
            )

    return row


def save_snapshot(db, row, user, note):
    db.add(
        ShelterUpdate(
            shelter_id=row.id,
            capacity=row.capacity,
            occupied=row.occupied,
            version=row.version,
            changed_by=user.id,
            note=note,
        )
    )


def create_managed_shelter(db, user, data):
    team = db.get(Team, data.team_id)

    if (
        team is None
        or team.team_type.casefold() != "shelter"
    ):
        raise HTTPException(
            409,
            "Select an existing Shelter team",
        )

    row = Shelter(**data.model_dump())
    if row.occupied >= row.capacity:
        row.status = "FULL"

    db.add(row)

    db.flush()

    save_snapshot(
        db,
        row,
        user,
        "Shelter created",
    )

    db.commit()

    return shelter_view(row)


def update_shelter(db, shelter_id, user, data):
    row = require_shelter(
        db,
        shelter_id,
        user=user,
        lock=True,
    )

    if row.version != data.expected_version:
        raise HTTPException(
            409,
            "Shelter changed; reload before updating",
        )

    row.capacity = data.capacity

    row.occupied = data.occupied

    if row.status != "CLOSED":
        row.status = "FULL" if row.occupied >= row.capacity else "OPEN"

    row.version += 1

    save_snapshot(
        db,
        row,
        user,
        data.note,
    )

    db.commit()

    return shelter_view(row)