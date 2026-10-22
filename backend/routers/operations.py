"""Authenticated operations API; every write repeats ownership checks in service."""
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from backend.database.connection import get_db
from backend.models.user import Role, User
from backend.schemas.operations_schema import (
    DeliveryCreate, InventoryCreate, InventoryUpdate, ReliefAssign, ReliefCreate,
    TaskHandoff, TaskNote, TaskProgress,
)
from backend.services import operations_service as service
from backend.utils.permissions import get_current_user, require_roles


router = APIRouter(prefix="/api/operations", tags=["Operations"])


@router.get("/inventory")
def inventory(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return service.list_inventory(db, user)


@router.post("/inventory", status_code=status.HTTP_201_CREATED)
def create_inventory(data: InventoryCreate, db: Session = Depends(get_db),
                     user: User = Depends(require_roles(Role.ADMIN))):
    return service.create_inventory(db, user, data)


@router.patch("/inventory/{item_id}")
def update_inventory(item_id: int, data: InventoryUpdate, db: Session = Depends(get_db),
                     user: User = Depends(require_roles(Role.ADMIN))):
    return service.update_inventory(db, user, item_id, data)


@router.get("/inventory/{item_id}/history")
def stock_history(item_id: int, db: Session = Depends(get_db),
                  user: User = Depends(require_roles(Role.ADMIN))):
    return service.inventory_history(db, user, item_id)


@router.get("/relief-requests")
def relief_requests(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return service.list_relief_requests(db, user)


@router.post("/relief-requests", status_code=status.HTTP_201_CREATED)
def create_relief(data: ReliefCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return service.create_relief_request(db, user, data)


@router.get("/relief-requests/{request_id}")
def relief_detail(request_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return service.relief_request_detail(db, user, request_id)


@router.post("/relief-requests/{request_id}/assign")
def assign_relief(request_id: int, data: ReliefAssign, db: Session = Depends(get_db),
                  user: User = Depends(require_roles(Role.ADMIN))):
    return service.assign_relief_request(db, user, request_id, data)


@router.post("/relief-requests/{request_id}/deliveries")
def record_delivery(request_id: int, data: DeliveryCreate, db: Session = Depends(get_db),
                    user: User = Depends(require_roles(Role.RESPONSE_TEAM))):
    return service.deliver_relief_request(db, user, request_id, data)


@router.post("/relief-requests/{request_id}/complete")
def complete_support(request_id: int, data: TaskNote, db: Session = Depends(get_db),
                     user: User = Depends(require_roles(Role.RESPONSE_TEAM))):
    return service.complete_relief_request(db, user, request_id, data)


@router.get("/tasks")
def tasks(db: Session = Depends(get_db), user: User = Depends(require_roles(Role.ADMIN, Role.RESPONSE_TEAM))):
    return service.list_tasks(db, user)


@router.get("/task-history")
def task_history(db: Session = Depends(get_db), user: User = Depends(require_roles(Role.ADMIN, Role.RESPONSE_TEAM))):
    return service.list_task_history(db, user)


@router.get("/incidents/{incident_id}/task")
def task_detail(incident_id: int, db: Session = Depends(get_db),
                 user: User = Depends(require_roles(Role.ADMIN, Role.RESPONSE_TEAM))):
    return service.incident_task_detail(db, user, incident_id)


@router.post("/incidents/{incident_id}/accept")
def accept_task(incident_id: int, data: TaskNote, db: Session = Depends(get_db),
                user: User = Depends(require_roles(Role.RESPONSE_TEAM))):
    return service.accept_task(db, user, incident_id, data)


@router.post("/incidents/{incident_id}/progress")
def progress_task(incident_id: int, data: TaskProgress, db: Session = Depends(get_db),
                  user: User = Depends(require_roles(Role.RESPONSE_TEAM))):
    return service.progress_task(db, user, incident_id, data)


@router.post("/incidents/{incident_id}/handoff")
def handoff_task(incident_id: int, data: TaskHandoff, db: Session = Depends(get_db),
                 user: User = Depends(require_roles(Role.ADMIN))):
    return service.handoff_task(db, user, incident_id, data)
