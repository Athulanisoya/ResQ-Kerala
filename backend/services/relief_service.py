from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend.models.relief import (
    Distribution,
    Inventory,
    ReliefRequest,
)

from backend.schemas.relief_schema import UNITS

from backend.services.response_service import add_service_history

from backend.utils.permissions import (
    require_assigned_service_team,
    require_incident_access,
)


def request_view(row):
    return {
        "id": row.id,
        "incident_id": row.incident_id,
        "item": row.item,
        "unit": UNITS[row.item],
        "quantity": row.quantity,
        "fulfilled": row.fulfilled,
        "remaining": row.quantity - row.fulfilled,
    }


def stock_view(row):
    return {
        "id": row.id,
        "item": row.item,
        "unit": UNITS[row.item],
        "quantity": row.quantity,
    }


def delivery_view(row):
    return {
        "id": row.id,
        "request_id": row.request_id,
        "team_id": row.team_id,
        "quantity": row.quantity,
        "idempotency_key": row.idempotency_key,
        "recorded_by": row.recorded_by,
        "created_at": row.created_at,
    }


def create_request(db, incident_id, user, data):
    incident = require_incident_access(
        db,
        incident_id,
        user,
        lock=True,
    )

    if incident.status in {"RESOLVED", "CLOSED"}:
        raise HTTPException(
            409,
            "This case no longer accepts relief requests",
        )

    existing = db.scalar(
        select(ReliefRequest.id).where(
            ReliefRequest.incident_id == incident_id,
            ReliefRequest.item == data.item,
        )
    )

    if existing is not None:
        raise HTTPException(
            409,
            "This incident already has a request for that item",
        )

    row = ReliefRequest(
        incident_id=incident_id,
        created_by=user.id,
        **data.model_dump(),
    )

    db.add(row)

    add_service_history(
        db,
        incident,
        (
            f"User {user.id} requested "
            f"{data.quantity} {UNITS[data.item]} of {data.item}"
        ),
    )

    db.commit()

    return request_view(row)


def create_stock(db, data):
    row = Inventory(**data.model_dump())

    db.add(row)

    try:
        db.commit()

    except IntegrityError:
        db.rollback()

        raise HTTPException(
            409,
            "Item already exists; use its restock endpoint",
        )

    return stock_view(row)


def restock(db, stock_id, data):
    row = db.scalar(
        select(Inventory)
        .where(Inventory.id == stock_id)
        .with_for_update()
    )

    if row is None:
        raise HTTPException(
            404,
            "Inventory item not found",
        )

    row.quantity += data.quantity

    db.commit()

    return stock_view(row)


def distribute(db, request_id, user, data):
    request = db.get(ReliefRequest, request_id)

    if request is None:
        raise HTTPException(
            404,
            "Relief request not found",
        )

    incident = require_incident_access(
        db,
        request.incident_id,
        user,
        lock=True,
    )

    require_assigned_service_team(
        db,
        incident,
        user,
        {"relief"},
    )

    request = db.scalar(
        select(ReliefRequest)
        .where(ReliefRequest.id == request_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )

    key = str(data.idempotency_key)

    prior = db.scalar(
        select(Distribution).where(
            Distribution.idempotency_key == key
        )
    )

    if prior is not None:
        if (
            prior.request_id != request_id
            or prior.quantity != data.quantity
            or prior.recorded_by != user.id
        ):
            raise HTTPException(
                409,
                "This delivery key was already used for different data",
            )

        return delivery_view(prior)

    if incident.status != "IN_PROGRESS":
        raise HTTPException(
            409,
            "Start the relief task before recording delivery",
        )

    stock = db.scalar(
        select(Inventory)
        .where(Inventory.item == request.item)
        .with_for_update()
    )

    if (
        stock is None
        or stock.quantity < data.quantity
    ):
        raise HTTPException(
            409,
            "Not enough matching inventory",
        )

    if data.quantity > request.quantity - request.fulfilled:
        raise HTTPException(
            409,
            "Delivery exceeds remaining demand",
        )

    stock.quantity -= data.quantity

    request.fulfilled += data.quantity

    delivery = Distribution(
        request_id=request.id,
        inventory_id=stock.id,
        team_id=user.team_id,
        recorded_by=user.id,
        quantity=data.quantity,
        idempotency_key=key,
    )

    db.add(delivery)

    add_service_history(
        db,
        incident,
        (
            f"Team {user.team_id} delivered "
            f"{data.quantity} {UNITS[request.item]} "
            f"of {request.item}"
        ),
    )

    try:
        db.commit()

    except IntegrityError:
        db.rollback()

        raise HTTPException(
            409,
            "Concurrent delivery conflict; refresh and retry with the same key",
        )

    return delivery_view(delivery)