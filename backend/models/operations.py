"""Athul's stock, distribution ledger and private assignment history."""
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint

from backend.database.connection import Base


class InventoryItem(Base):
    __tablename__ = "inventory_items"
    __table_args__ = (CheckConstraint("quantity >= 0", name="ck_inventory_nonnegative"),)
    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    unit = Column(String(40), nullable=False)
    quantity = Column(Numeric(14, 3), nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class InventoryAdjustment(Base):
    __tablename__ = "inventory_adjustments"
    id = Column(Integer, primary_key=True)
    inventory_item_id = Column(Integer, ForeignKey("inventory_items.id"), nullable=False, index=True)
    actor_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    item_name = Column(String(120), nullable=False)
    unit = Column(String(40), nullable=False)
    previous_quantity = Column(Numeric(14, 3), nullable=False)
    quantity = Column(Numeric(14, 3), nullable=False)
    reason = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class ReliefRequest(Base):
    __tablename__ = "relief_requests"
    id = Column(Integer, primary_key=True)
    incident_id = Column(Integer, ForeignKey("incident_reports.id"), nullable=False, index=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    kind = Column(String(30), nullable=False, default="SUPPLIES")
    note = Column(Text, nullable=True)
    status = Column(String(30), nullable=False, default="PENDING")
    assigned_team_id = Column(Integer, ForeignKey("response_teams.id"), nullable=True, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)


class ReliefRequestItem(Base):
    __tablename__ = "relief_request_items"
    __table_args__ = (
        UniqueConstraint("relief_request_id", "inventory_item_id", name="uq_relief_inventory_item"),
        CheckConstraint("requested_quantity > 0 AND delivered_quantity >= 0 AND delivered_quantity <= requested_quantity", name="ck_relief_quantities"),
    )
    id = Column(Integer, primary_key=True)
    relief_request_id = Column(Integer, ForeignKey("relief_requests.id"), nullable=False, index=True)
    inventory_item_id = Column(Integer, ForeignKey("inventory_items.id"), nullable=False)
    item_name = Column(String(120), nullable=False)
    unit = Column(String(40), nullable=False)
    requested_quantity = Column(Numeric(14, 3), nullable=False)
    delivered_quantity = Column(Numeric(14, 3), nullable=False, default=0)


class ReliefDelivery(Base):
    __tablename__ = "relief_deliveries"
    __table_args__ = (UniqueConstraint("relief_request_id", "idempotency_key", name="uq_relief_delivery_key"),)
    id = Column(Integer, primary_key=True)
    relief_request_id = Column(Integer, ForeignKey("relief_requests.id"), nullable=False, index=True)
    team_id = Column(Integer, ForeignKey("response_teams.id"), nullable=False)
    actor_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    idempotency_key = Column(String(100), nullable=False)
    payload_fingerprint = Column(String(64), nullable=False)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class ReliefDeliveryItem(Base):
    __tablename__ = "relief_delivery_items"
    __table_args__ = (CheckConstraint("quantity > 0", name="ck_delivery_positive"),)
    id = Column(Integer, primary_key=True)
    delivery_id = Column(Integer, ForeignKey("relief_deliveries.id"), nullable=False, index=True)
    request_item_id = Column(Integer, ForeignKey("relief_request_items.id"), nullable=False)
    inventory_item_id = Column(Integer, ForeignKey("inventory_items.id"), nullable=False)
    item_name = Column(String(120), nullable=False)
    unit = Column(String(40), nullable=False)
    quantity = Column(Numeric(14, 3), nullable=False)


class IncidentTask(Base):
    __tablename__ = "incident_tasks"
    id = Column(Integer, primary_key=True)
    incident_id = Column(Integer, ForeignKey("incident_reports.id"), nullable=False, index=True)
    team_id = Column(Integer, ForeignKey("response_teams.id"), nullable=False, index=True)
    team_name = Column(String(100), nullable=False)
    report_reference = Column(String(50), nullable=False)
    message = Column(Text, nullable=False)
    location = Column(String(255), nullable=False)
    help_required = Column(String(255), nullable=True)
    people_affected = Column(Integer, nullable=True)
    status = Column(String(30), nullable=False, default="ASSIGNED")
    active = Column(Boolean, nullable=False, default=True)
    assigned_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    accepted_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)


class IncidentTaskEvent(Base):
    __tablename__ = "incident_task_events"
    id = Column(Integer, primary_key=True)
    task_id = Column(Integer, ForeignKey("incident_tasks.id"), nullable=False, index=True)
    status = Column(String(30), nullable=False)
    note = Column(Text, nullable=True)
    actor_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
