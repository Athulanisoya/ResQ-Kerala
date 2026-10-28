from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.database.connection import get_db
from backend.models import Role, User

from backend.models.relief import (
    Distribution,
    Inventory,
    ReliefRequest,
)

from backend.schemas.relief_schema import (
    DeliveryInput,
    ReliefInput,
    StockAddition,
)

from backend.services import relief_service as service

from backend.utils.permissions import (
    get_current_user,
    require_incident_access,
    require_roles,
)


router = APIRouter(
    prefix="/api/relief",
    tags=["Week 3 - Relief"],
)


@router.post(
    "/incidents/{incident_id}/requests",
    status_code=201,
)
def request_relief(
    incident_id: int,
    data: ReliefInput,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return service.create_request(
        db,
        incident_id,
        user,
        data,
    )


@router.get("/incidents/{incident_id}/requests")
def list_requests(
    incident_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_incident_access(
        db,
        incident_id,
        user,
    )

    rows = db.scalars(
        select(ReliefRequest)
        .where(ReliefRequest.incident_id == incident_id)
        .order_by(ReliefRequest.id)
    )

    return [
        service.request_view(row)
        for row in rows
    ]


@router.get("/incidents/{incident_id}/distributions")
def list_deliveries(
    incident_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_incident_access(
        db,
        incident_id,
        user,
    )

    rows = db.scalars(
        select(Distribution)
        .join(ReliefRequest)
        .where(ReliefRequest.incident_id == incident_id)
        .order_by(Distribution.id)
    )

    return [
        service.delivery_view(row)
        for row in rows
    ]


@router.get("/inventory")
def inventory(
    db: Session = Depends(get_db),
    _user: User = Depends(
        require_roles(
            Role.ADMIN,
            Role.RESPONSE_TEAM,
        )
    ),
):
    rows = db.scalars(
        select(Inventory).order_by(Inventory.item)
    )

    return [
        service.stock_view(row)
        for row in rows
    ]


@router.post("/inventory", status_code=201)
def add_inventory(
    data: ReliefInput,
    db: Session = Depends(get_db),
    _user: User = Depends(
        require_roles(Role.ADMIN)
    ),
):
    return service.create_stock(db, data)


@router.post("/inventory/{stock_id}/restock")
def add_stock(
    stock_id: int,
    data: StockAddition,
    db: Session = Depends(get_db),
    _user: User = Depends(
        require_roles(Role.ADMIN)
    ),
):
    return service.restock(
        db,
        stock_id,
        data,
    )


@router.post("/requests/{request_id}/distributions")
def deliver(
    request_id: int,
    data: DeliveryInput,
    db: Session = Depends(get_db),
    user: User = Depends(
        require_roles(Role.RESPONSE_TEAM)
    ),
):
    return service.distribute(
        db,
        request_id,
        user,
        data,
    )