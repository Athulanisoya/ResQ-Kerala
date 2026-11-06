"""Existing reports survive the nullable retry-key upgrade on SQLite and PG."""
import os
from uuid import uuid4

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateSchema, DropSchema

from backend.database.offline_report_migrations import migrate_offline_reports


def check_migration(engine, schema=None):
    metadata = MetaData(schema=schema)
    incidents = Table("incident_reports", metadata, Column("id", Integer, primary_key=True),
                      Column("user_id", Integer, nullable=False), Column("message", String(200)))
    with engine.begin() as connection:
        metadata.create_all(connection)
        connection.execute(incidents.insert(), [{"id": 1, "user_id": 8, "message": "Retained original"},
                                               {"id": 2, "user_id": 8, "message": "Retained second original"}])
        migrate_offline_reports(connection, metadata)
        migrate_offline_reports(connection, metadata)
        reflected = Table("incident_reports", MetaData(), schema=schema, autoload_with=connection)
        old = list(connection.execute(select(reflected).order_by(reflected.c.id)).mappings())
        assert [row["message"] for row in old] == ["Retained original", "Retained second original"]
        assert all(row["client_submission_id"] is None and row["submission_fingerprint"] is None for row in old)
        key = str(uuid4())
        connection.execute(reflected.insert(), {"id": 3, "user_id": 8, "message": "Offline new", "client_submission_id": key})
        with pytest.raises(IntegrityError):
            with connection.begin_nested():
                connection.execute(reflected.insert(), {"id": 4, "user_id": 8, "message": "Duplicate", "client_submission_id": key})
        connection.execute(reflected.insert(), {"id": 5, "user_id": 9, "message": "Separate account", "client_submission_id": key})
        assert connection.execute(select(reflected.c.id).order_by(reflected.c.id)).all() == [(1,), (2,), (3,), (5,)]


def test_sqlite_retry_key_migration_preserves_existing_records():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        check_migration(engine)
    finally:
        engine.dispose()


def test_postgres_retry_key_migration_preserves_existing_records():
    url = os.environ.get("RESQ_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Set RESQ_TEST_POSTGRES_URL for isolated PostgreSQL offline migration checks.")
    engine = create_engine(url)
    schema = "resq_offline_migration_test_" + uuid4().hex
    created = False
    try:
        assert engine.dialect.name == "postgresql"
        with engine.begin() as connection:
            connection.execute(CreateSchema(schema))
        created = True
        check_migration(engine, schema)
    finally:
        if created:
            with engine.begin() as connection:
                connection.execute(DropSchema(schema, cascade=True, if_exists=True))
        engine.dispose()
