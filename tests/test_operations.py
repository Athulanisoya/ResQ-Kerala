"""Athul Week 3: real API validation, task privacy and all-or-nothing stock."""
import os
from dataclasses import dataclass
from decimal import Decimal

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["ALLOW_SQLITE_FOR_TESTS"] = "true"
os.environ["JWT_SECRET"] = "synthetic-operations-tests-only-secret-2026"

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database.connection import Base, get_db
from backend.models import Incident, IncidentStatusHistory, Role, Team, User
from backend.models.communication import Notification
from backend.models.operations import IncidentTask, IncidentTaskEvent, InventoryAdjustment, InventoryItem, ReliefDelivery, ReliefRequest, ReliefRequestItem
from backend.routers import incidents, operations
from backend.utils.permissions import get_current_user


@dataclass
class Harness:
    client: TestClient
    sessions: object
    users: dict
    teams: dict
    incident_id: int

    def request(self, method, path, json=None, user="admin"):
        headers = {"X-Test-User": user} if user else {}
        return self.client.request(method, f"/api/operations{path}", json=json, headers=headers)

    def assign(self):
        response = self.client.post("/api/incidents/admin/assign-team", headers={"X-Test-User": "admin"},
            json={"incident_id": self.incident_id, "team_id": self.teams["rescue"]})
        assert response.status_code == 200, response.text
        return response.json()

    def accept(self, user="rescue"):
        return self.request("POST", f"/incidents/{self.incident_id}/accept", {}, user)

    def progress(self, status, user="rescue"):
        return self.request("POST", f"/incidents/{self.incident_id}/progress", {"status": status}, user)

    def in_progress(self):
        self.assign()
        assert self.accept().status_code == 200
        assert self.progress("EN_ROUTE").status_code == 200
        assert self.progress("IN_PROGRESS").status_code == 200

    def inventory(self, name="Rice", unit="kg", quantity=20):
        result = self.request("POST", "/inventory", {"name": name, "unit": unit, "quantity": quantity})
        assert result.status_code == 201, result.text
        return result.json()

    def relief(self, items, kind="SUPPLIES", user="citizen"):
        result = self.request("POST", "/relief-requests", {"incident_id": self.incident_id,
                               "kind": kind, "items": items}, user)
        assert result.status_code == 201, result.text
        return result.json()

    def supplies(self, quantity=10, stock=20):
        item = self.inventory(quantity=stock)
        request = self.relief([{"inventory_item_id": item["id"], "quantity": quantity, "unit": item["unit"]}])
        result = self.request("POST", f"/relief-requests/{request['id']}/assign", {"team_id": self.teams["relief"]})
        assert result.status_code == 200, result.text
        return item, result.json()

    def deliver(self, request, amount, key="first-delivery-1", unit=None, user="relief"):
        return self.request("POST", f"/relief-requests/{request['id']}/deliveries", {
            "idempotency_key": key, "items": [{"request_item_id": request["items"][0]["id"],
                        "quantity": amount, "unit": unit or request["items"][0]["unit"]}]}, user)


@pytest.fixture
def ops():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def constraints(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as db:
        teams = {name: Team(name=f"Synthetic {name}", team_type=kind, status="AVAILABLE")
                 for name, kind in {"rescue": "Rescue", "relief": "Relief", "other": "Rescue", "investigation": "Investigation"}.items()}
        db.add_all(teams.values())
        db.flush()
        users = {name: User(full_name=f"Synthetic {name}", email=f"{name}@example.com",
                           password_hash="unused-synthetic-hash", role=role,
                           team_id=teams[name].id if name in teams else None)
                 for name, role in {"admin": Role.ADMIN, "citizen": Role.CITIZEN,
                    "stranger": Role.CITIZEN, "rescue": Role.RESPONSE_TEAM, "relief": Role.RESPONSE_TEAM,
                    "other": Role.RESPONSE_TEAM, "unaffiliated": Role.RESPONSE_TEAM}.items()}
        db.add_all(users.values())
        db.flush()
        incident = Incident(report_reference="RESQ OPS PRIVATE", user_id=users["citizen"].id,
                            message="Original water rescue report", location="Original location", status="VERIFIED")
        db.add(incident)
        db.commit()
        user_ids = {name: row.id for name, row in users.items()}
        team_ids = {name: row.id for name, row in teams.items()}
        incident_id = incident.id
    app = FastAPI()
    app.include_router(operations.router)
    app.include_router(incidents.router)

    def database():
        with sessions() as db:
            yield db

    def current_user(x_test_user: str | None = Header(default=None)):
        if x_test_user not in user_ids:
            raise HTTPException(401, "Authentication required")
        with sessions() as db:
            return db.get(User, user_ids[x_test_user])

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_user] = current_user
    try:
        with TestClient(app) as client:
            yield Harness(client, sessions, user_ids, team_ids, incident_id)
    finally:
        engine.dispose()


def test_explicit_task_acceptance_retries_and_ordered_progress_release_team(ops):
    ops.assign()
    assert ops.progress("EN_ROUTE").status_code == 409
    accepted = ops.accept()
    assert accepted.status_code == 200, accepted.text
    first = accepted.json()
    assert first["status"] == "TASK_ACCEPTED" and first["accepted_at"]
    repeated = ops.request("POST", f"/incidents/{ops.incident_id}/accept", {"note": "Retry note cannot replace audit"}, "rescue")
    assert repeated.json() == first
    assert ops.progress("RESOLVED").status_code == 409
    assert ops.progress("EN_ROUTE").status_code == 200
    assert ops.accept().json()["accepted_at"] == first["accepted_at"]
    assert ops.progress("IN_PROGRESS").status_code == 200
    resolved = ops.progress("RESOLVED")
    assert resolved.status_code == 200 and resolved.json()["active"] is False
    assert ops.progress("IN_PROGRESS").status_code == 409
    with ops.sessions() as db:
        assert db.get(Team, ops.teams["rescue"]).status == "AVAILABLE"
        incident = db.get(Incident, ops.incident_id)
        assert incident.status == "RESOLVED" and incident.assigned_team_id == ops.teams["rescue"]
        events = db.scalars(select(IncidentTaskEvent).where(IncidentTaskEvent.status == "TASK_ACCEPTED")).all()
        assert len(events) == 1
        assert len(db.scalars(select(Notification).where(Notification.title == "Task accepted")).all()) == 3
    assert ops.request("GET", "/tasks", user="rescue").json() == []


@pytest.mark.parametrize("user,expected", [(None, 401), ("citizen", 403), ("stranger", 403), ("admin", 403), ("other", 403), ("unaffiliated", 403)])
def test_only_assigned_team_can_accept_or_progress(ops, user, expected):
    ops.assign()
    assert ops.accept(user).status_code == expected
    assert ops.progress("EN_ROUTE", user).status_code == expected


def test_handoff_retains_private_snapshot_and_releases_only_after_valid_successor(ops):
    ops.in_progress()
    path = f"/incidents/{ops.incident_id}/handoff"
    payload = {"team_id": ops.teams["relief"], "note": "Rescue complete; supplies still required"}
    assert ops.request("POST", path, payload, "rescue").status_code == 403
    with ops.sessions() as db:
        db.get(Team, ops.teams["relief"]).status = "BUSY"
        db.commit()
    assert ops.request("POST", path, payload).status_code == 409
    with ops.sessions() as db:
        assert db.get(Incident, ops.incident_id).assigned_team_id == ops.teams["rescue"]
        assert db.get(Team, ops.teams["rescue"]).status == "BUSY"
        db.get(Team, ops.teams["relief"]).status = "AVAILABLE"
        db.commit()
    handed = ops.request("POST", path, payload)
    assert handed.status_code == 200, handed.text
    assert handed.json()["team_id"] == ops.teams["relief"]
    assert handed.json()["status"] == "ASSIGNED" and handed.json()["accepted_at"] is None
    assert ops.request("POST", path, payload).status_code == 409
    with ops.sessions() as db:
        assert db.get(Team, ops.teams["rescue"]).status == "AVAILABLE"
        incident = db.get(Incident, ops.incident_id)
        incident.message = "PRIVATE later report update"
        incident.location = "PRIVATE later location"
        db.commit()
    history = ops.request("GET", "/task-history", user="rescue").json()
    assert len(history) == 1 and history[0]["status"] == "HANDED_OFF"
    assert history[0]["message"] == "Original water rescue report"
    assert history[0]["location"] == "Original location"
    assert "PRIVATE later" not in str(history)
    assert ops.request("GET", "/tasks", user="rescue").json() == []
    assert ops.request("GET", f"/incidents/{ops.incident_id}/task", user="rescue").status_code == 403
    assert ops.client.get(f"/api/incidents/{ops.incident_id}", headers={"X-Test-User": "rescue"}).status_code == 403
    assert ops.request("GET", "/task-history", user="other").json() == []
    assert ops.accept("relief").status_code == 200


def test_inventory_catalogue_audit_and_immutable_referenced_item_identity(ops):
    item = ops.inventory(quantity="3.125")
    catalogue = ops.request("GET", "/inventory", user="citizen").json()
    assert catalogue == [{"id": item["id"], "name": "Rice", "unit": "kg"}]
    assert ops.request("PATCH", f"/inventory/{item['id']}", {"quantity": "4.125", "reason": "New donation received"}).status_code == 200
    request = ops.relief([{"inventory_item_id": item["id"], "unit": "kg", "quantity": 6}])
    for changes in ({"unit": "packs"}, {"name": "Wheat"}):
        assert ops.request("PATCH", f"/inventory/{item['id']}", changes).status_code == 409
    assert request["items"][0]["item_name"] == "Rice"
    history = ops.request("GET", f"/inventory/{item['id']}/history").json()
    assert len(history) == 2 and history[-1]["previous_quantity"] == 3.125
    assert history[-1]["quantity"] == 4.125 and history[-1]["reason"] == "New donation received"
    assert ops.request("GET", f"/inventory/{item['id']}/history", user="citizen").status_code == 403
    assert ops.request("PATCH", f"/inventory/{item['id']}", {"quantity": 5}, "rescue").status_code == 403


def test_partial_delivery_remaining_demand_stock_and_idempotent_final_delivery(ops):
    item, request = ops.supplies(quantity=10, stock=20)
    first = ops.deliver(request, "3.125")
    assert first.status_code == 200, first.text
    data = first.json()
    assert data["status"] == "PARTIALLY_DELIVERED"
    assert data["items"][0]["remaining_quantity"] == 6.875
    assert data["deliveries"][0]["items"][0]["item_name"] == "Rice"
    assert ops.deliver(request, "3.125").json() == data
    assert ops.deliver(request, 2).status_code == 409  # same key, changed payload
    final = ops.deliver(request, "6.875", "second-delivery-2")
    assert final.status_code == 200, final.text
    assert final.json()["status"] == "COMPLETED"
    assert final.json()["items"][0]["remaining_quantity"] == 0
    assert ops.deliver(request, "6.875", "second-delivery-2").json() == final.json()
    assert ops.deliver(request, 1, "third-delivery-3").status_code == 409
    with ops.sessions() as db:
        assert db.get(InventoryItem, item["id"]).quantity == Decimal(10)
        assert db.scalar(select(func.count(ReliefDelivery.id))) == 2
        assert db.scalar(select(func.count(InventoryAdjustment.id))) == 3
        assert db.get(Team, ops.teams["relief"]).status == "AVAILABLE"


def test_multi_item_insufficient_stock_rolls_back_entire_basket(ops):
    rice = ops.inventory(quantity=20)
    water = ops.inventory("Drinking water", "litres", 1)
    request = ops.relief([{"inventory_item_id": rice["id"], "quantity": 5, "unit": "kg"},
                          {"inventory_item_id": water["id"], "quantity": 5, "unit": "litres"}])
    assert ops.request("POST", f"/relief-requests/{request['id']}/assign", {"team_id": ops.teams["relief"]}).status_code == 200
    response = ops.request("POST", f"/relief-requests/{request['id']}/deliveries", {
        "idempotency_key": "failed-basket-01", "items": [
            {"request_item_id": request["items"][0]["id"], "quantity": 2, "unit": "kg"},
            {"request_item_id": request["items"][1]["id"], "quantity": 2, "unit": "litres"}]}, "relief")
    assert response.status_code == 409
    with ops.sessions() as db:
        assert db.get(InventoryItem, rice["id"]).quantity == 20
        assert db.get(InventoryItem, water["id"]).quantity == 1
        assert all(row.delivered_quantity == 0 for row in db.scalars(select(ReliefRequestItem)))
        assert db.scalar(select(func.count(ReliefDelivery.id))) == 0


@pytest.mark.parametrize("failure", ["unit", "stock", "remaining", "foreign-line"])
def test_delivery_rejects_bad_unit_overselling_overdelivery_or_foreign_item(ops, failure):
    item, request = ops.supplies(quantity=4, stock=3)
    payload = {"idempotency_key": "rejected-delivery", "items": [{"request_item_id": request["items"][0]["id"],
                                                       "quantity": 2, "unit": "kg"}]}
    if failure == "unit":
        payload["items"][0]["unit"] = "packs"
    elif failure == "stock":
        payload["items"][0]["quantity"] = 4
    elif failure == "remaining":
        payload["items"][0]["quantity"] = 5
    else:
        payload["items"][0]["request_item_id"] += 100
    response = ops.request("POST", f"/relief-requests/{request['id']}/deliveries", payload, "relief")
    assert response.status_code == 409
    with ops.sessions() as db:
        assert db.get(InventoryItem, item["id"]).quantity == 3
        assert db.scalar(select(func.count(ReliefDelivery.id))) == 0


def test_assignment_type_and_private_relief_access(ops):
    item = ops.inventory()
    request = ops.relief([{"inventory_item_id": item["id"], "quantity": 10, "unit": "kg"}])
    assert ops.request("POST", f"/relief-requests/{request['id']}/assign", {"team_id": ops.teams["rescue"]}).status_code == 409
    assert ops.request("POST", f"/relief-requests/{request['id']}/assign", {"team_id": ops.teams["investigation"]}).status_code == 409
    assert ops.request("POST", f"/relief-requests/{request['id']}/assign", {"team_id": ops.teams["relief"]}).status_code == 200
    assert ops.request("POST", f"/relief-requests/{request['id']}/assign", {"team_id": ops.teams["relief"]}).status_code == 409
    assert ops.request("GET", "/relief-requests", user="stranger").json() == []
    assert ops.request("GET", f"/relief-requests/{request['id']}", user="stranger").status_code == 403
    assert ops.request("GET", f"/relief-requests/{request['id']}", user="other").status_code == 403
    assert ops.deliver(request, 1, user="rescue").status_code == 403
    assert ops.deliver(request, 1, user="admin").status_code == 403
    assert ops.deliver(request, 1, user="citizen").status_code == 403


def test_relief_team_receives_assignment_and_delivery_updates_while_rescue_owns_report(ops):
    ops.in_progress()
    _item, request = ops.supplies(quantity=2)
    assert ops.deliver(request, 1).status_code == 200
    with ops.sessions() as db:
        assert db.get(Incident, ops.incident_id).assigned_team_id == ops.teams["rescue"]
        updates = list(db.scalars(select(Notification).where(
            Notification.title.in_(["Relief team assigned", "Relief delivery recorded"]))))
        for title in ("Relief team assigned", "Relief delivery recorded"):
            recipients = {row.user_id for row in updates if row.title == title}
            assert recipients == {ops.users[name] for name in ("admin", "citizen", "rescue", "relief")}
        assert ops.users["other"] not in {row.user_id for row in updates}


def test_unfinished_relief_blocks_resolution_and_rescue_support_blocks_handoff(ops):
    ops.in_progress()
    support = ops.relief([], kind="RESCUE_SUPPORT")
    assert ops.progress("RESOLVED").status_code == 409
    assert ops.request("POST", f"/incidents/{ops.incident_id}/handoff", {
        "team_id": ops.teams["relief"], "note": "Waiting for a safe handoff"}).status_code == 409
    assert ops.request("POST", f"/relief-requests/{support['id']}/assign", {"team_id": ops.teams["rescue"]}).status_code == 200
    assert ops.request("POST", f"/relief-requests/{support['id']}/complete", {}, "rescue").status_code == 200
    assert ops.progress("RESOLVED").status_code == 200
    response = ops.request("POST", "/relief-requests", {"incident_id": ops.incident_id,
                           "kind": "RESCUE_SUPPORT"}, "citizen")
    assert response.status_code == 409


@pytest.mark.parametrize("payload", [
    {"name": "Rice", "unit": "kg", "quantity": -1},
    {"name": "Rice", "unit": "kg", "quantity": "0.0001"},
    {"name": "Rice", "unit": "kg", "quantity": "NaN"},
    {"name": "Rice", "unit": "kg", "quantity": "Infinity"},
    {"name": "Rice", "unit": " "},
])
def test_inventory_rejects_invalid_stock_or_units(ops, payload):
    assert ops.request("POST", "/inventory", payload).status_code == 422


def test_duplicate_request_and_delivery_lines_rejected_before_mutation(ops):
    item, request = ops.supplies()
    line = {"inventory_item_id": item["id"], "quantity": 1, "unit": "kg"}
    assert ops.request("POST", "/relief-requests", {"incident_id": ops.incident_id, "items": [line, line]}).status_code == 422
    delivery_line = {"request_item_id": request["items"][0]["id"], "quantity": 1, "unit": "kg"}
    assert ops.request("POST", f"/relief-requests/{request['id']}/deliveries", {
        "idempotency_key": "duplicate-lines-01", "items": [delivery_line, delivery_line]}, "relief").status_code == 422
