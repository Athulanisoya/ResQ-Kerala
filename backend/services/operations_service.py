"""Transactional rescue progress and stock-safe relief distribution.

Assignment snapshots are the only source for a former team's history. They never
join back to a report after handoff, so later citizen/admin edits remain private.
"""
from datetime import datetime
from decimal import Decimal
from functools import wraps
from hashlib import sha256
import json

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.incident import Incident, IncidentStatusHistory
from backend.models.operations import (
    IncidentTask, IncidentTaskEvent, InventoryAdjustment, InventoryItem,
    ReliefDelivery, ReliefDeliveryItem, ReliefRequest, ReliefRequestItem,
)
from backend.models.team import Team
from backend.models.user import Role, User


FINAL_STATUSES = {"RESOLVED", "CLOSED"}


def atomic(function):
    @wraps(function)
    def transaction(db, *args, **kwargs):
        try:
            result = function(db, *args, **kwargs)
            db.commit()
            return result
        except Exception:
            db.rollback()
            raise
    return transaction


def _deny(detail="You do not have permission for this action."):
    raise HTTPException(403, detail)


def _admin(user):
    if user.role != Role.ADMIN:
        _deny()


def _team(user):
    if user.role != Role.RESPONSE_TEAM or user.team_id is None:
        _deny("A response team membership is required.")


def _locked(db, model, identifier, detail):
    record = db.scalar(select(model).where(model.id == identifier)
                       .with_for_update().execution_options(populate_existing=True))
    if record is None:
        raise HTTPException(404, detail)
    return record


def _incident(db, incident_id, user, *, lock=False):
    record = _locked(db, Incident, incident_id, "Incident not found") if lock else db.get(Incident, incident_id)
    if record is None:
        raise HTTPException(404, "Incident not found")
    if not (user.role == Role.ADMIN or
            (user.role == Role.CITIZEN and record.user_id == user.id) or
            (user.role == Role.RESPONSE_TEAM and user.team_id is not None and record.assigned_team_id == user.team_id)):
        _deny("You are not allowed to access this incident.")
    return record


def _notify(db, incident, title, message, event_key=None, extra_team_ids=()):
    from backend.services.communication_service import notify_incident
    notify_incident(db, incident, title, message, event_key=event_key, extra_team_ids=extra_team_ids)


def inventory_dict(item):
    return {"id": item.id, "name": item.name, "unit": item.unit,
            "quantity": float(item.quantity), "updated_at": item.updated_at}


def list_inventory(db: Session, user: User):
    if user.role not in {Role.ADMIN, Role.RESPONSE_TEAM, Role.CITIZEN}:
        _deny()
    # Citizens need the public catalogue to select a requested item and its unit;
    # actual stock and audit entries remain operational information.
    records = db.scalars(select(InventoryItem).order_by(InventoryItem.name, InventoryItem.id)).all()
    if user.role == Role.CITIZEN:
        return [{"id": row.id, "name": row.name, "unit": row.unit} for row in records]
    return [inventory_dict(row) for row in records]


def _audit_stock(db, item, user, previous, reason):
    db.add(InventoryAdjustment(inventory_item_id=item.id, actor_user_id=user.id,
                              item_name=item.name, unit=item.unit,
                              previous_quantity=previous, quantity=item.quantity, reason=reason))


@atomic
def create_inventory(db: Session, user: User, data):
    _admin(user)
    item = InventoryItem(name=data.name, unit=data.unit, quantity=data.quantity)
    db.add(item)
    db.flush()
    _audit_stock(db, item, user, Decimal(0), data.reason)
    db.flush()
    return inventory_dict(item)


@atomic
def update_inventory(db: Session, user: User, item_id: int, data):
    _admin(user)
    item = _locked(db, InventoryItem, item_id, "Inventory item not found")
    referenced = db.scalar(select(ReliefRequestItem.id).where(ReliefRequestItem.inventory_item_id == item.id).limit(1))
    if referenced is not None and data.unit is not None and data.unit != item.unit:
        raise HTTPException(409, "A referenced item's unit cannot change. Create a new inventory item.")
    # Item identity is immutable after the first request. Names on existing
    # request/delivery records are snapshots even for later catalogue changes.
    if referenced is not None and data.name is not None and data.name != item.name:
        raise HTTPException(409, "A referenced item's name cannot change. Create a new inventory item.")
    previous = item.quantity
    for key in ("name", "unit", "quantity"):
        value = getattr(data, key)
        if value is not None:
            setattr(item, key, value)
    _audit_stock(db, item, user, previous, data.reason)
    db.flush()
    return inventory_dict(item)


def inventory_history(db: Session, user: User, item_id: int):
    _admin(user)
    if db.get(InventoryItem, item_id) is None:
        raise HTTPException(404, "Inventory item not found")
    return [{"id": row.id, "actor_user_id": row.actor_user_id, "item_name": row.item_name,
             "unit": row.unit, "previous_quantity": float(row.previous_quantity),
             "quantity": float(row.quantity), "reason": row.reason, "created_at": row.created_at}
            for row in db.scalars(select(InventoryAdjustment).where(
                InventoryAdjustment.inventory_item_id == item_id).order_by(InventoryAdjustment.id))]


def _request_access(db, record, user):
    if user.role == Role.ADMIN:
        return
    if user.role == Role.RESPONSE_TEAM and user.team_id is not None and record.assigned_team_id == user.team_id:
        return
    _incident(db, record.incident_id, user)


def _request(db, request_id, user, *, lock=False):
    record = db.get(ReliefRequest, request_id)
    if record is None:
        raise HTTPException(404, "Relief request not found")
    if lock:
        # Incident then request is the universal lock order, including case
        # closure, so no request can be inserted/delivered across closure.
        _locked(db, Incident, record.incident_id, "Incident not found")
        record = _locked(db, ReliefRequest, request_id, "Relief request not found")
    _request_access(db, record, user)
    return record


def relief_dict(db, record, *, include_deliveries=True):
    lines = db.scalars(select(ReliefRequestItem).where(
        ReliefRequestItem.relief_request_id == record.id).order_by(ReliefRequestItem.id)).all()
    incident = db.get(Incident, record.incident_id)
    team = db.get(Team, record.assigned_team_id) if record.assigned_team_id else None
    result = {"id": record.id, "incident_id": record.incident_id,
              "report_reference": incident.report_reference if incident else None,
              "kind": record.kind, "note": record.note, "status": record.status,
              "assigned_team_id": record.assigned_team_id, "assigned_team_name": team.name if team else None,
              "created_at": record.created_at, "completed_at": record.completed_at,
              "items": [{"id": row.id, "inventory_item_id": row.inventory_item_id,
                         "item_name": row.item_name, "unit": row.unit,
                         "requested_quantity": float(row.requested_quantity),
                         "delivered_quantity": float(row.delivered_quantity),
                         "remaining_quantity": float(row.requested_quantity - row.delivered_quantity)} for row in lines]}
    if include_deliveries:
        deliveries = db.scalars(select(ReliefDelivery).where(ReliefDelivery.relief_request_id == record.id)
                                .order_by(ReliefDelivery.id)).all()
        result["deliveries"] = [delivery_dict(db, row) for row in deliveries]
    return result


def delivery_dict(db, delivery):
    lines = db.scalars(select(ReliefDeliveryItem).where(ReliefDeliveryItem.delivery_id == delivery.id)
                       .order_by(ReliefDeliveryItem.id)).all()
    return {"id": delivery.id, "idempotency_key": delivery.idempotency_key,
            "team_id": delivery.team_id, "note": delivery.note, "created_at": delivery.created_at,
            "items": [{"request_item_id": row.request_item_id, "inventory_item_id": row.inventory_item_id,
                       "item_name": row.item_name, "unit": row.unit, "quantity": float(row.quantity)} for row in lines]}


def list_relief_requests(db: Session, user: User):
    query = select(ReliefRequest).join(Incident, Incident.id == ReliefRequest.incident_id)
    if user.role == Role.CITIZEN:
        query = query.where(Incident.user_id == user.id)
    elif user.role == Role.RESPONSE_TEAM:
        if user.team_id is None:
            return []
        query = query.where((ReliefRequest.assigned_team_id == user.team_id) |
                            (Incident.assigned_team_id == user.team_id))
    elif user.role != Role.ADMIN:
        _deny()
    return [relief_dict(db, row) for row in db.scalars(query.order_by(ReliefRequest.id.desc()))]


def relief_request_detail(db: Session, user: User, request_id: int):
    return relief_dict(db, _request(db, request_id, user))


@atomic
def create_relief_request(db: Session, user: User, data):
    incident = _incident(db, data.incident_id, user, lock=True)
    if incident.status in FINAL_STATUSES:
        raise HTTPException(409, "Resolved or closed reports cannot receive new relief requests.")
    items = {}
    for line in sorted(data.items, key=lambda value: value.inventory_item_id):
        item = _locked(db, InventoryItem, line.inventory_item_id, "Inventory item not found")
        if line.unit != item.unit:
            raise HTTPException(409, "Requested unit does not match the inventory item.")
        items[item.id] = item
    record = ReliefRequest(incident_id=incident.id, created_by_user_id=user.id,
                           kind=data.kind, note=data.note, status="PENDING")
    db.add(record)
    db.flush()
    for line in data.items:
        item = items[line.inventory_item_id]
        db.add(ReliefRequestItem(relief_request_id=record.id, inventory_item_id=item.id,
                                item_name=item.name, unit=item.unit,
                                requested_quantity=line.quantity, delivered_quantity=0))
    db.flush()
    _notify(db, incident, "Relief requested", f"A {record.kind.lower().replace('_', ' ')} request was recorded.",
            event_key=f"relief:{record.id}:created")
    return relief_dict(db, record)


def _team_available_for_incident(db, team, incident_id):
    other_incident = db.scalar(select(Incident.id).where(Incident.assigned_team_id == team.id,
                               Incident.id != incident_id, Incident.status.notin_(FINAL_STATUSES)).limit(1))
    other_request = db.scalar(select(ReliefRequest.id).where(ReliefRequest.assigned_team_id == team.id,
                              ReliefRequest.incident_id != incident_id, ReliefRequest.status != "COMPLETED").limit(1))
    if other_incident is not None or other_request is not None:
        return False
    if team.status == "AVAILABLE":
        return True
    # A BUSY team can take linked support on its own current incident only.
    return (db.scalar(select(Incident.id).where(Incident.id == incident_id, Incident.assigned_team_id == team.id)) is not None or
            db.scalar(select(ReliefRequest.id).where(ReliefRequest.incident_id == incident_id,
                ReliefRequest.assigned_team_id == team.id, ReliefRequest.status != "COMPLETED").limit(1)) is not None)


def release_team_if_idle(db: Session, team_id: int | None):
    if team_id is None:
        return
    db.flush()
    team = _locked(db, Team, team_id, "Response team not found")
    active_incident = db.scalar(select(Incident.id).where(Incident.assigned_team_id == team_id,
                               Incident.status.notin_(FINAL_STATUSES)).limit(1))
    active_relief = db.scalar(select(ReliefRequest.id).where(ReliefRequest.assigned_team_id == team_id,
                             ReliefRequest.status != "COMPLETED").limit(1))
    if active_incident is None and active_relief is None:
        team.status = "AVAILABLE"


@atomic
def assign_relief_request(db: Session, user: User, request_id: int, data):
    _admin(user)
    record = _request(db, request_id, user, lock=True)
    incident = db.get(Incident, record.incident_id)
    if record.status != "PENDING" or record.assigned_team_id is not None:
        raise HTTPException(409, "Only an unassigned pending relief request can be assigned.")
    if incident.status in {"SUBMITTED", "UNDER_REVIEW", *FINAL_STATUSES}:
        raise HTTPException(409, "Verify the incident before assigning relief.")
    team = _locked(db, Team, data.team_id, "Response team not found")
    required_type = "relief" if record.kind == "SUPPLIES" else "rescue"
    if team.team_type.strip().lower() != required_type:
        raise HTTPException(409, f"This request requires a {required_type} team.")
    if not _team_available_for_incident(db, team, incident.id):
        raise HTTPException(409, "This team is already assigned to another operation.")
    record.assigned_team_id = team.id
    record.status = "ASSIGNED"
    team.status = "BUSY"
    db.flush()
    _notify(db, incident, "Relief team assigned", f"{team.name} was assigned to relief request #{record.id}.",
            event_key=f"relief:{record.id}:assigned:{team.id}", extra_team_ids=[record.assigned_team_id])
    return relief_dict(db, record)


def unfinished_relief(db: Session, incident_id: int) -> bool:
    db.flush()
    from backend.models.relief import ReliefRequest as LegacyReliefRequest
    return (
        db.scalar(select(ReliefRequest.id).where(ReliefRequest.incident_id == incident_id,
                  ReliefRequest.status != "COMPLETED").limit(1)) is not None
        or db.scalar(select(LegacyReliefRequest.id).where(
            LegacyReliefRequest.incident_id == incident_id,
            LegacyReliefRequest.fulfilled < LegacyReliefRequest.quantity).limit(1)) is not None
    )


@atomic
def deliver_relief_request(db: Session, user: User, request_id: int, data):
    _team(user)
    record = _request(db, request_id, user, lock=True)
    if record.assigned_team_id != user.team_id:
        _deny("Only the assigned relief team can record deliveries.")
    if record.kind != "SUPPLIES":
        raise HTTPException(409, "Rescue support is completed without inventory delivery.")
    canonical = {"items": sorted([{"request_item_id": row.request_item_id,
                   "quantity": str(row.quantity.normalize()), "unit": row.unit} for row in data.items],
                   key=lambda row: row["request_item_id"]), "note": data.note}
    fingerprint = sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()
    existing = db.scalar(select(ReliefDelivery).where(ReliefDelivery.relief_request_id == record.id,
                         ReliefDelivery.idempotency_key == data.idempotency_key))
    if existing is not None:
        if existing.payload_fingerprint != fingerprint:
            raise HTTPException(409, "The delivery key has already been used for a different delivery.")
        return relief_dict(db, record)
    if record.status not in {"ASSIGNED", "PARTIALLY_DELIVERED"}:
        raise HTTPException(409, "This request is not awaiting a delivery.")
    incident = db.get(Incident, record.incident_id)
    if incident.status in FINAL_STATUSES:
        raise HTTPException(409, "This incident is already resolved or closed.")
    lines = {row.id: row for row in db.scalars(select(ReliefRequestItem).where(
        ReliefRequestItem.relief_request_id == record.id).order_by(ReliefRequestItem.id).with_for_update()
        .execution_options(populate_existing=True))}
    if any(row.request_item_id not in lines for row in data.items):
        raise HTTPException(409, "A delivery item does not belong to this relief request.")
    inventory_ids = sorted({lines[row.request_item_id].inventory_item_id for row in data.items})
    stock = {identifier: _locked(db, InventoryItem, identifier, "Inventory item not found") for identifier in inventory_ids}
    # Validate the complete basket before changing any stock or demand.
    for row in data.items:
        line = lines[row.request_item_id]
        item = stock[line.inventory_item_id]
        if row.unit != line.unit or row.unit != item.unit:
            raise HTTPException(409, "Delivery unit does not match the immutable request unit.")
        if row.quantity > line.requested_quantity - line.delivered_quantity:
            raise HTTPException(409, "Delivery exceeds the remaining requested quantity.")
        if row.quantity > item.quantity:
            raise HTTPException(409, f"Insufficient stock for {line.item_name}.")
    delivery = ReliefDelivery(relief_request_id=record.id, team_id=user.team_id,
                             actor_user_id=user.id, idempotency_key=data.idempotency_key,
                             payload_fingerprint=fingerprint, note=data.note)
    db.add(delivery)
    db.flush()
    for row in data.items:
        line = lines[row.request_item_id]
        item = stock[line.inventory_item_id]
        previous = item.quantity
        item.quantity -= row.quantity
        line.delivered_quantity += row.quantity
        db.add(ReliefDeliveryItem(delivery_id=delivery.id, request_item_id=line.id,
                                 inventory_item_id=item.id, item_name=line.item_name,
                                 unit=line.unit, quantity=row.quantity))
        _audit_stock(db, item, user, previous, f"Relief delivery #{delivery.id}, request #{record.id}")
    record.status = "COMPLETED" if all(row.delivered_quantity == row.requested_quantity for row in lines.values()) else "PARTIALLY_DELIVERED"
    if record.status == "COMPLETED":
        record.completed_at = datetime.utcnow()
    db.flush()
    release_team_if_idle(db, user.team_id)
    _notify(db, incident, "Relief delivery recorded",
            f"Delivery #{delivery.id} recorded. Request #{record.id}: {record.status.replace('_', ' ').lower()}.",
            event_key=f"relief-delivery:{delivery.id}", extra_team_ids=[record.assigned_team_id])
    return relief_dict(db, record)


@atomic
def complete_relief_request(db: Session, user: User, request_id: int, data):
    _team(user)
    record = _request(db, request_id, user, lock=True)
    if record.assigned_team_id != user.team_id:
        _deny("Only the assigned rescue team can complete support.")
    if record.kind != "RESCUE_SUPPORT" or record.status != "ASSIGNED":
        raise HTTPException(409, "Only assigned rescue support can be completed here.")
    incident = db.get(Incident, record.incident_id)
    if incident.status in FINAL_STATUSES:
        raise HTTPException(409, "This incident is already resolved or closed.")
    record.status = "COMPLETED"
    record.completed_at = datetime.utcnow()
    db.flush()
    release_team_if_idle(db, user.team_id)
    _notify(db, incident, "Rescue support completed", data.note or "Assigned rescue support was completed.",
            event_key=f"relief:{record.id}:completed", extra_team_ids=[record.assigned_team_id])
    return relief_dict(db, record)


def capture_assignment(db: Session, incident: Incident, team: Team, note=None, actor_user_id=None):
    """Flush-only hook used in the original assignment transaction."""
    task = IncidentTask(incident_id=incident.id, team_id=team.id, team_name=team.name,
                        report_reference=incident.report_reference, message=incident.message,
                        location=incident.location, help_required=incident.help_required,
                        people_affected=incident.people_affected, status=incident.status, active=True)
    db.add(task)
    db.flush()
    db.add(IncidentTaskEvent(task_id=task.id, status=incident.status,
                            note=note or f"Assigned to {team.name}", actor_user_id=actor_user_id))
    return task


def _current_task(db, incident):
    task = db.scalar(select(IncidentTask).where(IncidentTask.incident_id == incident.id,
                     IncidentTask.team_id == incident.assigned_team_id, IncidentTask.active.is_(True))
                     .order_by(IncidentTask.id.desc()).with_for_update().execution_options(populate_existing=True))
    if task is None:
        # Existing Week 2 assignments predate task snapshots; capture on the first
        # authorised mutation while the incident is locked.
        team = db.get(Team, incident.assigned_team_id)
        task = capture_assignment(db, incident, team, "Existing assignment imported")
    return task


def _record_progress(db, incident, task, user, status, note):
    incident.status = status
    task.status = status
    db.add(IncidentStatusHistory(incident_id=incident.id, status=status, note=note))
    db.add(IncidentTaskEvent(task_id=task.id, status=status, note=note, actor_user_id=user.id))


def task_dict(db, task):
    return {"id": task.id, "incident_id": task.incident_id, "team_id": task.team_id,
            "team_name": task.team_name, "report_reference": task.report_reference,
            "message": task.message, "location": task.location,
            "help_required": task.help_required, "people_affected": task.people_affected,
            "status": task.status, "active": task.active,
            "assigned_at": task.assigned_at, "accepted_at": task.accepted_at, "ended_at": task.ended_at,
            "events": [{"id": row.id, "status": row.status, "note": row.note,
                        "created_at": row.created_at} for row in db.scalars(select(IncidentTaskEvent)
                .where(IncidentTaskEvent.task_id == task.id).order_by(IncidentTaskEvent.id))]}


def _current_task_dict(db, incident):
    task = db.scalar(select(IncidentTask).where(IncidentTask.incident_id == incident.id,
                     IncidentTask.team_id == incident.assigned_team_id)
                     .order_by(IncidentTask.id.desc()))
    if task is not None:
        result = task_dict(db, task)
        result["status"] = incident.status
        return result
    team = db.get(Team, incident.assigned_team_id)
    return {"id": None, "incident_id": incident.id, "team_id": incident.assigned_team_id,
            "team_name": team.name if team else "Assigned team", "report_reference": incident.report_reference,
            "message": incident.message, "location": incident.location, "help_required": incident.help_required,
            "people_affected": incident.people_affected, "status": incident.status, "active": True,
            "assigned_at": incident.updated_at, "accepted_at": None, "ended_at": None, "events": []}


def list_tasks(db: Session, user: User):
    if user.role not in {Role.ADMIN, Role.RESPONSE_TEAM}:
        _deny()
    query = select(Incident).where(Incident.assigned_team_id.is_not(None), Incident.status.notin_(FINAL_STATUSES))
    if user.role == Role.RESPONSE_TEAM:
        if user.team_id is None:
            return []
        query = query.where(Incident.assigned_team_id == user.team_id)
    return [_current_task_dict(db, row) for row in db.scalars(query.order_by(Incident.updated_at.desc(), Incident.id.desc()))]


def incident_task_detail(db: Session, user: User, incident_id: int):
    incident = _incident(db, incident_id, user)
    if user.role == Role.CITIZEN:
        _deny()
    return _current_task_dict(db, incident) if incident.assigned_team_id else None


def list_task_history(db: Session, user: User):
    if user.role not in {Role.ADMIN, Role.RESPONSE_TEAM}:
        _deny()
    query = select(IncidentTask)
    if user.role == Role.RESPONSE_TEAM:
        if user.team_id is None:
            return []
        query = query.where(IncidentTask.team_id == user.team_id)
    return [task_dict(db, row) for row in db.scalars(query.order_by(IncidentTask.id.desc()))]


@atomic
def accept_task(db: Session, user: User, incident_id: int, data):
    _team(user)
    incident = _incident(db, incident_id, user, lock=True)
    if incident.assigned_team_id != user.team_id:
        _deny()
    existing = db.scalar(select(IncidentTask).where(IncidentTask.incident_id == incident.id,
                         IncidentTask.team_id == user.team_id).order_by(IncidentTask.id.desc())
                         .execution_options(populate_existing=True))
    if existing is not None and existing.accepted_at is not None and incident.status in {
            "ACCEPTED", "TASK_ACCEPTED", "EN_ROUTE", "IN_PROGRESS", "RESCUE_COMPLETED", "RESOLVED", "CLOSED"}:
        # Network/form retries retain the original acceptance timestamp, note,
        # event and notification even when the team has already progressed.
        return task_dict(db, existing)
    if incident.status != "ASSIGNED":
        raise HTTPException(409, "Only an assigned, unaccepted task can be accepted.")
    task = _current_task(db, incident)
    task.accepted_at = datetime.utcnow()
    _record_progress(db, incident, task, user, "TASK_ACCEPTED", data.note or "Team accepted the task")
    db.flush()
    _notify(db, incident, "Task accepted", f"{task.team_name} accepted the task.", event_key=f"task:{task.id}:accepted")
    return task_dict(db, task)


@atomic
def progress_task(db: Session, user: User, incident_id: int, data):
    _team(user)
    incident = _incident(db, incident_id, user, lock=True)
    if incident.assigned_team_id != user.team_id:
        _deny()
    transitions = {"ACCEPTED": "EN_ROUTE", "TASK_ACCEPTED": "EN_ROUTE", "EN_ROUTE": "IN_PROGRESS", "IN_PROGRESS": "RESOLVED", "RESCUE_COMPLETED": "RESOLVED"}
    if transitions.get(incident.status) != data.status:
        raise HTTPException(409, "Follow task acceptance, en route, in progress, then resolved in order.")
    if data.status == "RESOLVED" and unfinished_relief(db, incident.id):
        raise HTTPException(409, "Complete all linked relief requests before resolving this report.")
    task = _current_task(db, incident)
    _record_progress(db, incident, task, user, data.status,
                     data.note or f"Team marked the task {data.status.replace('_', ' ').lower()}")
    if data.status == "RESOLVED":
        task.active = False
        task.ended_at = datetime.utcnow()
        release_team_if_idle(db, user.team_id)
    db.flush()
    _notify(db, incident, "Response progress updated", f"{task.team_name}: {data.status.replace('_', ' ').lower()}.",
            event_key=f"task:{task.id}:{data.status}")
    return task_dict(db, task)


@atomic
def handoff_task(db: Session, user: User, incident_id: int, data):
    _admin(user)
    incident = _incident(db, incident_id, user, lock=True)
    if incident.status not in {"IN_PROGRESS", "RESCUE_COMPLETED"} or incident.assigned_team_id is None:
        raise HTTPException(409, "A rescue-to-relief handoff requires an in-progress assigned rescue task.")
    if data.team_id == incident.assigned_team_id:
        raise HTTPException(409, "Select a different relief team for handoff.")
    teams = {identifier: _locked(db, Team, identifier, "Response team not found")
             for identifier in sorted({incident.assigned_team_id, data.team_id})}
    previous = teams[incident.assigned_team_id]
    successor = teams[data.team_id]
    if previous.team_type.strip().lower() != "rescue" or successor.team_type.strip().lower() != "relief":
        raise HTTPException(409, "Handoff must be from a rescue team to a relief team.")
    if not _team_available_for_incident(db, successor, incident.id):
        raise HTTPException(409, "The successor relief team is already assigned elsewhere.")
    pending_rescue = db.scalar(select(ReliefRequest.id).where(ReliefRequest.incident_id == incident.id,
                   ReliefRequest.kind == "RESCUE_SUPPORT", ReliefRequest.status != "COMPLETED").limit(1))
    if pending_rescue is not None:
        raise HTTPException(409, "Complete linked rescue support before handing off to relief.")
    task = _current_task(db, incident)
    task.status = "HANDED_OFF"
    task.active = False
    task.ended_at = datetime.utcnow()
    db.add(IncidentTaskEvent(task_id=task.id, status="HANDED_OFF", note=data.note, actor_user_id=user.id))
    incident.assigned_team_id = successor.id
    incident.status = "ASSIGNED"
    successor.status = "BUSY"
    db.add(IncidentStatusHistory(incident_id=incident.id, status="ASSIGNED",
        note=f"Admin handoff from {previous.name} to {successor.name}: {data.note}"))
    successor_task = capture_assignment(db, incident, successor, data.note, user.id)
    release_team_if_idle(db, previous.id)
    db.flush()
    _notify(db, incident, "Response handoff completed", f"{previous.name} handed off to {successor.name}.",
            event_key=f"task:{successor_task.id}:handoff")
    return task_dict(db, successor_task)
