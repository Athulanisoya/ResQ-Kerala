"""Opt-in real PostgreSQL transactions; only a random test schema is touched.

Set RESQ_TEST_POSTGRES_URL. Independent sessions contend on the same stock/task
rows, so SQLite's no-op FOR UPDATE cannot accidentally pass the race checks.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from decimal import Decimal
import os
from threading import Barrier
from uuid import uuid4

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["ALLOW_SQLITE_FOR_TESTS"] = "true"
os.environ["JWT_SECRET"] = "synthetic-operations-postgres-tests-secret-2026"

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import CreateSchema, DropSchema

from backend.database.connection import Base
from backend.models import Incident, Role, Team, User
from backend.models.operations import IncidentTask, IncidentTaskEvent, InventoryItem, ReliefDelivery, ReliefRequest, ReliefRequestItem
from backend.schemas.operations_schema import DeliveryCreate, InventoryCreate, ReliefAssign, ReliefCreate, TaskHandoff, TaskNote, TaskProgress
from backend.services import operations_service as service
from backend.services.communication_service import close_incident
from backend.services.incident_service import assign_incident_team


@dataclass
class PgHarness:
    sessions: object
    users: dict
    teams: dict
    incidents: list

    def call(self, name, user="admin", *args):
        with self.sessions() as db:
            return getattr(service, name)(db, db.get(User, self.users[user]), *args)

    def assign(self, incident_id=None):
        with self.sessions() as db:
            assign_incident_team(db, incident_id or self.incidents[0], self.teams["rescue"])

    def stock(self, quantity=5):
        return self.call("create_inventory", "admin", InventoryCreate(name="Rice", unit="kg", quantity=quantity))

    def request(self, item, incident_id=None, user="citizen", quantity=4, team="relief"):
        request = self.call("create_relief_request", user, ReliefCreate(incident_id=incident_id or self.incidents[0],
                     items=[{"inventory_item_id": item["id"], "unit": "kg", "quantity": quantity}]))
        return self.call("assign_relief_request", "admin", request["id"], ReliefAssign(team_id=self.teams[team]))

    @staticmethod
    def delivery(request, quantity, key):
        return DeliveryCreate(idempotency_key=key, items=[{"request_item_id": request["items"][0]["id"],
                            "unit": "kg", "quantity": quantity}])


@pytest.fixture
def pg_ops():
    url = os.environ.get("RESQ_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Set RESQ_TEST_POSTGRES_URL for isolated PostgreSQL operations concurrency checks.")
    engine = create_engine(url, connect_args={"options": "-c lock_timeout=10000 -c statement_timeout=20000"})
    if engine.dialect.name != "postgresql":
        engine.dispose()
        pytest.fail("RESQ_TEST_POSTGRES_URL must select PostgreSQL.")
    schema = f"resq_operations_test_{uuid4().hex}"
    bound = engine.execution_options(schema_translate_map={Base.metadata.schema: schema})
    created = False
    try:
        with engine.begin() as connection:
            connection.execute(CreateSchema(schema))
        created = True
        Base.metadata.create_all(bound)
        sessions = sessionmaker(bind=bound, expire_on_commit=False, autoflush=False)
        with sessions() as db:
            teams = {name: Team(name=f"Synthetic PG {name}", team_type=kind, status="AVAILABLE")
                     for name, kind in {"rescue": "Rescue", "relief": "Relief", "relief2": "Relief"}.items()}
            db.add_all(teams.values())
            db.flush()
            users = {name: User(full_name=f"Synthetic PG {name}", email=f"pg-{name}@example.com",
                               password_hash="synthetic-unused-hash", role=role,
                               team_id=teams[name].id if name in teams else None)
                     for name, role in {"admin": Role.ADMIN, "citizen": Role.CITIZEN,
                         "citizen2": Role.CITIZEN, "rescue": Role.RESPONSE_TEAM,
                         "relief": Role.RESPONSE_TEAM, "relief2": Role.RESPONSE_TEAM}.items()}
            db.add_all(users.values())
            db.flush()
            incidents = [Incident(report_reference=f"RESQ PG OPS {index}", user_id=users[owner].id,
                                  message=f"Synthetic PostgreSQL incident {index}", location="Kochi", status="VERIFIED")
                         for index, owner in enumerate(["citizen", "citizen2"])]
            db.add_all(incidents)
            db.commit()
            yield PgHarness(sessions, {name: row.id for name, row in users.items()},
                            {name: row.id for name, row in teams.items()}, [row.id for row in incidents])
    finally:
        if created:
            # Only the exact randomly named test schema created above is removed.
            with engine.begin() as connection:
                connection.execute(DropSchema(schema, cascade=True, if_exists=True))
        engine.dispose()


def race(functions):
    barrier = Barrier(len(functions))

    def run(function):
        barrier.wait(timeout=15)
        try:
            return 200, function()
        except HTTPException as error:
            return error.status_code, error.detail

    with ThreadPoolExecutor(max_workers=len(functions)) as pool:
        futures = [pool.submit(run, function) for function in functions]
        return [future.result(timeout=35) for future in futures]


def test_postgres_complete_rescue_relief_delivery_resolution_and_closure(pg_ops):
    pg = pg_ops
    incident_id = pg.incidents[0]
    item = pg.stock(20)
    pg.assign()
    accepted = pg.call("accept_task", "rescue", incident_id, TaskNote(note="Responders accepted rescue"))
    assert accepted["status"] == "TASK_ACCEPTED"
    for status in ("EN_ROUTE", "IN_PROGRESS"):
        pg.call("progress_task", "rescue", incident_id, TaskProgress(status=status))
    request = pg.call("create_relief_request", "citizen", ReliefCreate(incident_id=incident_id,
                        items=[{"inventory_item_id": item["id"], "quantity": 10, "unit": "kg"}]))
    with pytest.raises(HTTPException) as unresolved:
        pg.call("progress_task", "rescue", incident_id, TaskProgress(status="RESOLVED"))
    assert unresolved.value.status_code == 409
    handoff = pg.call("handoff_task", "admin", incident_id,
                       TaskHandoff(team_id=pg.teams["relief"], note="Rescue complete; relief will finish supply distribution"))
    assert handoff["status"] == "ASSIGNED" and handoff["accepted_at"] is None
    with pytest.raises(HTTPException) as forbidden:
        pg.call("incident_task_detail", "rescue", incident_id)
    assert forbidden.value.status_code == 403
    old = pg.call("list_task_history", "rescue")
    assert len(old) == 1 and old[0]["status"] == "HANDED_OFF"
    pg.call("assign_relief_request", "admin", request["id"], ReliefAssign(team_id=pg.teams["relief"]))
    pg.call("accept_task", "relief", incident_id, TaskNote())
    for status in ("EN_ROUTE", "IN_PROGRESS"):
        pg.call("progress_task", "relief", incident_id, TaskProgress(status=status))
    partial = pg.call("deliver_relief_request", "relief", request["id"], pg.delivery(request, "3.125", "pg-partial-01"))
    assert partial["status"] == "PARTIALLY_DELIVERED" and partial["items"][0]["remaining_quantity"] == 6.875
    with pytest.raises(HTTPException):
        pg.call("progress_task", "relief", incident_id, TaskProgress(status="RESOLVED"))
    completed = pg.call("deliver_relief_request", "relief", request["id"], pg.delivery(request, "6.875", "pg-final-002"))
    assert completed["status"] == "COMPLETED" and completed["items"][0]["remaining_quantity"] == 0
    assert all(line["item_name"] == "Rice" and line["unit"] == "kg"
               for delivery in completed["deliveries"] for line in delivery["items"])
    pg.call("progress_task", "relief", incident_id, TaskProgress(status="RESOLVED"))
    with pg.sessions() as db:
        assert db.get(InventoryItem, item["id"]).quantity == Decimal(10)
        assert db.get(Team, pg.teams["rescue"]).status == "AVAILABLE"
        assert db.get(Team, pg.teams["relief"]).status == "AVAILABLE"
        closed = close_incident(db, incident_id, db.get(User, pg.users["admin"]), "All assistance confirmed complete")
        assert closed["status"] == "CLOSED"
    with pg.sessions() as db:
        assert db.get(Incident, incident_id).status == "CLOSED"
        assert not service.unfinished_relief(db, incident_id)


def test_postgres_competing_deliveries_cannot_oversell_shared_stock(pg_ops):
    pg = pg_ops
    item = pg.stock(5)
    request1 = pg.request(item, quantity=4)
    request2 = pg.request(item, incident_id=pg.incidents[1], user="citizen2", quantity=4, team="relief2")
    results = race([
        lambda: pg.call("deliver_relief_request", "relief", request1["id"], pg.delivery(request1, 4, "pg-race-first")),
        lambda: pg.call("deliver_relief_request", "relief2", request2["id"], pg.delivery(request2, 4, "pg-race-second")),
    ])
    assert sorted(result[0] for result in results) == [200, 409]
    with pg.sessions() as db:
        assert db.get(InventoryItem, item["id"]).quantity == Decimal(1)
        assert db.scalar(select(func.count(ReliefDelivery.id))) == 1
        assert sorted(row.delivered_quantity for row in db.scalars(select(ReliefRequestItem))) == [0, 4]
        assert sorted(row.status for row in db.scalars(select(ReliefRequest))) == ["ASSIGNED", "COMPLETED"]


def test_postgres_duplicate_delivery_retry_is_exactly_once(pg_ops):
    pg = pg_ops
    item = pg.stock(10)
    request = pg.request(item, quantity=4)
    payload = pg.delivery(request, 4, "pg-duplicate-retry")
    results = race([lambda: pg.call("deliver_relief_request", "relief", request["id"], payload),
                    lambda: pg.call("deliver_relief_request", "relief", request["id"], payload)])
    assert [result[0] for result in results] == [200, 200]
    assert results[0][1] == results[1][1]
    with pg.sessions() as db:
        assert db.get(InventoryItem, item["id"]).quantity == Decimal(6)
        assert db.scalar(select(func.count(ReliefDelivery.id))) == 1


def test_postgres_competing_accept_retries_and_progress_do_not_duplicate_history(pg_ops):
    pg = pg_ops
    pg.assign()
    incident_id = pg.incidents[0]
    accepted = race([lambda: pg.call("accept_task", "rescue", incident_id, TaskNote()),
                     lambda: pg.call("accept_task", "rescue", incident_id, TaskNote())])
    assert [result[0] for result in accepted] == [200, 200]
    assert accepted[0][1] == accepted[1][1]
    progressed = race([lambda: pg.call("progress_task", "rescue", incident_id, TaskProgress(status="EN_ROUTE")),
                       lambda: pg.call("progress_task", "rescue", incident_id, TaskProgress(status="EN_ROUTE"))])
    assert sorted(result[0] for result in progressed) == [200, 409]
    with pg.sessions() as db:
        assert db.get(Incident, incident_id).status == "EN_ROUTE"
        assert db.scalar(select(func.count(IncidentTaskEvent.id)).where(IncidentTaskEvent.status == "TASK_ACCEPTED")) == 1
        assert db.scalar(select(func.count(IncidentTaskEvent.id)).where(IncidentTaskEvent.status == "EN_ROUTE")) == 1


def test_postgres_competing_handoffs_leave_one_successor_and_snapshot(pg_ops):
    pg = pg_ops
    pg.assign()
    incident_id = pg.incidents[0]
    pg.call("accept_task", "rescue", incident_id, TaskNote())
    for status in ("EN_ROUTE", "IN_PROGRESS"):
        pg.call("progress_task", "rescue", incident_id, TaskProgress(status=status))
    results = race([
        lambda: pg.call("handoff_task", "admin", incident_id, TaskHandoff(team_id=pg.teams["relief"], note="Safe relief handoff one")),
        lambda: pg.call("handoff_task", "admin", incident_id, TaskHandoff(team_id=pg.teams["relief2"], note="Safe relief handoff two")),
    ])
    assert sorted(result[0] for result in results) == [200, 409]
    with pg.sessions() as db:
        incident = db.get(Incident, incident_id)
        assert incident.status == "ASSIGNED"
        assert db.get(Team, pg.teams["rescue"]).status == "AVAILABLE"
        tasks = list(db.scalars(select(IncidentTask).where(IncidentTask.incident_id == incident_id)))
        assert len(tasks) == 2 and sum(task.active for task in tasks) == 1
        assert next(task for task in tasks if task.active).team_id == incident.assigned_team_id
