from fastapi import HTTPException
from sqlalchemy import select

from backend.models import Role, Team
from backend.models.shelter import Shelter, ShelterUpdate


def shelter_view(row):
    return {
        "id": row.id,
        "name": row.name,
        "location": row.location,
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


def create_shelter(db, user, data):
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

    row.version += 1

    save_snapshot(
        db,
        row,
        user,
        data.note,
    )

    db.commit()

    return shelter_view(row)