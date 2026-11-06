"""Data-preserving legacy upgrades and reminder deduplication on real PostgreSQL."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import os
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import Column, DateTime, ForeignKey, Integer, MetaData, String, Table, Text, UniqueConstraint, create_engine, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateSchema, DropSchema

# Select synthetic app settings before importing application models. Only the
# explicit test URL below connects to PostgreSQL, in a randomly named schema.
from test_operations_postgres import pg_ops
from backend.database.automation_migrations import migrate_automations
from backend.models.automation import ShelterReminderState
from backend.models.communication import Notification
from backend.models.shelter import Shelter
from backend.services.shelter_reminder_service import process_shelter_reminders, utc


@pytest.fixture
def legacy_schema():
    url = os.environ.get("RESQ_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Set RESQ_TEST_POSTGRES_URL for legacy automation migration checks.")
    engine = create_engine(url)
    if engine.dialect.name != "postgresql":
        engine.dispose()
        pytest.fail("RESQ_TEST_POSTGRES_URL must select PostgreSQL.")
    schema = "resq_auto_migration_test_" + uuid4().hex
    metadata = MetaData(schema=schema)
    users = Table("users", metadata, Column("id", Integer, primary_key=True), Column("role", String(30), nullable=False))
    incidents = Table("incident_reports", metadata, Column("id", Integer, primary_key=True))
    notifications = Table("incident_notifications", metadata,
        Column("id", Integer, primary_key=True), Column("user_id", Integer, ForeignKey(users.c.id, ondelete="CASCADE"), nullable=False),
        Column("incident_id", Integer, ForeignKey(incidents.c.id, ondelete="CASCADE"), nullable=False),
        Column("title", String(120), nullable=False), Column("message", Text, nullable=False),
        Column("event_key", String(255)), Column("created_at", DateTime(timezone=True), nullable=False),
        Column("read_at", DateTime(timezone=True)), UniqueConstraint("user_id", "event_key"))
    shelters = Table("shelters", metadata, Column("id", Integer, primary_key=True),
        Column("name", String(160), nullable=False), Column("capacity", Integer, nullable=False),
        Column("occupied", Integer, nullable=False), Column("status", String(10), nullable=False),
        Column("updated_at", DateTime(timezone=True), nullable=False))
    updates = Table("shelter_updates", metadata, Column("id", Integer, primary_key=True),
        Column("shelter_id", Integer, ForeignKey(shelters.c.id), nullable=False),
        Column("capacity", Integer, nullable=False), Column("occupied", Integer, nullable=False),
        Column("version", Integer, nullable=False), Column("note", String(1000), nullable=False),
        Column("changed_by", Integer, ForeignKey(users.c.id), nullable=False),
        Column("created_at", DateTime, nullable=False))
    created = False
    try:
        with engine.begin() as connection:
            connection.execute(CreateSchema(schema))
            created = True
            metadata.create_all(connection)
            connection.execute(users.insert(), [{"id": 1, "role": "admin"}, {"id": 2, "role": "response_team"}, {"id": 3, "role": "citizen"}])
            connection.execute(incidents.insert(), [{"id": 77}])
            connection.execute(notifications.insert(), [
                {"id": 42, "user_id": 3, "incident_id": 77, "title": "Synthetic retained read update", "message": "Original private incident update.",
                 "event_key": "incident:77:synthetic:read", "created_at": datetime(2026, 11, 1, tzinfo=timezone.utc), "read_at": datetime(2026, 11, 2, tzinfo=timezone.utc)},
                {"id": 43, "user_id": 1, "incident_id": 77, "title": "Synthetic retained unread update", "message": "Original administrator incident update.",
                 "event_key": "incident:77:synthetic:unread", "created_at": datetime(2026, 11, 1, tzinfo=timezone.utc), "read_at": None},
            ])
            connection.execute(shelters.insert(), [{"id": ident, "name": f"Synthetic legacy shelter {ident}", "capacity": 20,
                "occupied": 2, "status": "OPEN", "updated_at": datetime(2026, 11, 4, tzinfo=timezone.utc)} for ident in range(1, 5)])
            records = [
                (1, 1, 1, "Staff capacity confirmation", 1),
                (2, 1, 2, "Reception head count confirmed", 2),
                (3, 1, 1, "Registration #50: cancelled; spaces released", 3),
                (4, 1, 1, "Waitlist #51: offer expired", 4),
                (5, 1, 3, "Citizen activity cannot confirm capacity", 5),
                (6, 2, 3, "Citizen-only history", 1),
                (7, 2, 2, "Registration #52: arrival recorded", 2),
                (8, 4, 2, "Shelter reception confirmation", 1),
                (9, 4, 1, "Waitlist #53: held capacity changed", 5),
            ]
            connection.execute(updates.insert(), [{"id": ident, "shelter_id": shelter_id, "changed_by": actor,
                "capacity": 20, "occupied": 2, "version": ident, "note": note,
                "created_at": datetime(2026, 11, 1, hour)} for ident, shelter_id, actor, note, hour in records])
        yield engine, metadata, notifications, shelters, updates
    finally:
        if created:
            # The only recursive database operation is on this exact schema,
            # generated and created by this fixture in this test run.
            with engine.begin() as connection:
                connection.execute(DropSchema(schema, cascade=True, if_exists=True))
        engine.dispose()


def test_legacy_incident_notification_ids_privacy_read_state_and_foreign_keys_survive(legacy_schema):
    engine, metadata, notifications, shelters, updates = legacy_schema
    with engine.begin() as connection:
        before = [dict(row) for row in connection.execute(select(notifications).order_by(notifications.c.id)).mappings()]
        migrate_automations(connection, metadata)
        migrate_automations(connection, metadata)
        after = [dict(row) for row in connection.execute(select(notifications).order_by(notifications.c.id)).mappings()]
        assert after == before
        columns = {column["name"]: column for column in inspect(connection).get_columns("incident_notifications", schema=metadata.schema)}
        assert columns["incident_id"]["nullable"] and "target_url" in columns
        keys = inspect(connection).get_foreign_keys("incident_notifications", schema=metadata.schema)
        assert any(key["constrained_columns"] == ["incident_id"] and key["referred_table"] == "incident_reports"
                   and key["options"].get("ondelete") == "CASCADE" for key in keys)
        assert any(key["constrained_columns"] == ["user_id"] and key["referred_table"] == "users" for key in keys)
        reflected = Table("incident_notifications", MetaData(), schema=metadata.schema, autoload_with=connection)
        connection.execute(reflected.insert(), {"id": 44, "user_id": 3, "incident_id": None, "title": "Synthetic area notification",
            "message": "Generic in-app notice.", "event_key": "synthetic:area", "target_url": "/alerts",
            "created_at": datetime(2026, 11, 5, tzinfo=timezone.utc)})
        generic = connection.execute(select(reflected).where(reflected.c.id == 44)).mappings().one()
        assert generic["incident_id"] is None and generic["target_url"] == "/alerts" and generic["user_id"] == 3
        with pytest.raises(IntegrityError):
            with connection.begin_nested():
                connection.execute(reflected.insert(), {"id": 45, "user_id": 3, "incident_id": 999999,
                    "title": "Synthetic invalid reference", "message": "Must fail its retained foreign key.",
                    "created_at": datetime(2026, 11, 5, tzinfo=timezone.utc)})


def test_backfill_uses_only_staff_capacity_snapshots_and_allows_system_actor_without_reconfirming(legacy_schema):
    engine, metadata, notifications, shelters, updates = legacy_schema
    with engine.begin() as connection:
        old_shelters = [dict(row) for row in connection.execute(select(shelters).order_by(shelters.c.id)).mappings()]
        old_updates = [dict(row) for row in connection.execute(select(updates).order_by(updates.c.id)).mappings()]
        migrate_automations(connection, metadata)
        reflected = Table("shelters", MetaData(), schema=metadata.schema, autoload_with=connection)
        confirms = dict(connection.execute(select(reflected.c.id, reflected.c.capacity_confirmed_at)).all())
        assert confirms == {1: datetime(2026, 11, 1, 2, tzinfo=timezone.utc), 2: None, 3: None,
                            4: datetime(2026, 11, 1, 1, tzinfo=timezone.utc)}
        assert [dict(row) for row in connection.execute(select(shelters).order_by(shelters.c.id)).mappings()] == old_shelters
        assert [dict(row) for row in connection.execute(select(updates).order_by(updates.c.id)).mappings()] == old_updates
        changed_by = next(column for column in inspect(connection).get_columns("shelter_updates", schema=metadata.schema)
                          if column["name"] == "changed_by")
        assert changed_by["nullable"]
        keys = inspect(connection).get_foreign_keys("shelter_updates", schema=metadata.schema)
        assert any(key["constrained_columns"] == ["changed_by"] and key["referred_table"] == "users" for key in keys)
        connection.execute(updates.insert(), {"id": 100, "shelter_id": 1, "capacity": 20, "occupied": 1,
            "version": 100, "note": "Waitlist #100: automated release", "changed_by": None,
            "created_at": datetime(2026, 11, 5)})
        confirmed_later = datetime(2026, 11, 5, 7, tzinfo=timezone.utc)
        connection.execute(reflected.update().where(reflected.c.id == 1).values(capacity_confirmed_at=confirmed_later))
        migrate_automations(connection, metadata)
        assert connection.scalar(select(reflected.c.capacity_confirmed_at).where(reflected.c.id == 1)) == confirmed_later
        assert connection.scalar(select(updates.c.changed_by).where(updates.c.id == 100)) is None


def test_two_reminder_workers_send_one_event_for_a_stale_unstaffed_shelter(pg_ops):
    now = datetime.now(timezone.utc)
    confirmed = now - timedelta(minutes=45)
    with pg_ops.sessions() as db:
        shelter = Shelter(name="Synthetic concurrent reminder shelter", location="Aluva", capacity=8,
            occupied=2, status="OPEN", version=1, updated_at=now, capacity_confirmed_at=confirmed)
        db.add(shelter)
        db.commit()
        shelter_id = shelter.id
    barrier = Barrier(2)

    def worker():
        with pg_ops.sessions() as db:
            barrier.wait(timeout=10)
            result = process_shelter_reminders(db, now=now)
            db.commit()
            return result["admin_notifications"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker), pool.submit(worker)]
        assert sum(future.result(timeout=30) for future in futures) == 1
    with pg_ops.sessions() as db:
        records = db.scalars(select(Notification)).all()
        assert len(records) == 1 and records[0].user_id == pg_ops.users["admin"] and records[0].incident_id is None
        state = db.get(ShelterReminderState, shelter_id)
        assert state.sequence == 1 and utc(state.last_notified_at) == now and utc(state.last_escalated_at) == now
        shelter = db.get(Shelter, shelter_id)
        assert shelter.occupied == 2 and shelter.version == 1
        assert utc(shelter.updated_at) == now and utc(shelter.capacity_confirmed_at) == confirmed
