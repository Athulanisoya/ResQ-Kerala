"""Membership constraints and opt-in PostgreSQL migration checks.

PostgreSQL tests require RESQ_TEST_POSTGRES_URL and use only a unique temporary
schema, removed at teardown. They never migrate the configured app schema.
"""
import os
from uuid import uuid4

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["ALLOW_SQLITE_FOR_TESTS"] = "true"
os.environ["JWT_SECRET"] = "synthetic-membership-tests-only-secret-2026"

import pytest
from sqlalchemy import Column, ForeignKey, Integer, MetaData, String, Table, create_engine, event, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from backend.database.connection import Base
from backend.database.migrations import USER_TEAM_CONSTRAINT, ensure_user_team_foreign_key
from backend.models import Role, Team, User


@pytest.fixture
def membership_database():
    engine = create_engine("sqlite+pysqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_constraints(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            yield db
    finally:
        engine.dispose()


def account(**changes):
    return User(full_name="Synthetic Team Member", email="member@example.com",
                password_hash="synthetic-unused-hash", role=Role.RESPONSE_TEAM, **changes)


def test_dangling_membership_cannot_be_inserted(membership_database):
    db = membership_database
    db.add(account(team_id=999999))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    assert db.scalar(select(User)) is None


def test_valid_membership_relationship_and_dangling_update(membership_database):
    db = membership_database
    team = Team(name="Synthetic Membership Team", team_type="Rescue")
    member = account(team=team)
    db.add(member)
    db.commit()
    member_id, team_id = member.id, team.id
    assert member.team_id == team_id
    assert member.team is team

    member.team_id = 999999
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    assert db.get(User, member_id).team_id == team_id


def test_referenced_team_cannot_be_deleted(membership_database):
    db = membership_database
    team = Team(name="Synthetic Referenced Team", team_type="Rescue")
    member = account(team=team)
    db.add(member)
    db.commit()
    member_id, team_id = member.id, team.id

    db.delete(team)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    assert db.get(Team, team_id) is not None
    assert db.get(User, member_id).team_id == team_id


def test_account_without_membership_still_allowed(membership_database):
    db = membership_database
    member = account()
    db.add(member)
    db.commit()
    assert member.team_id is None
    assert member.team is None


@pytest.fixture
def postgres_legacy_schema():
    url = os.environ.get("RESQ_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Set RESQ_TEST_POSTGRES_URL to run isolated PostgreSQL migration checks.")
    engine = create_engine(url)
    if engine.dialect.name != "postgresql":
        engine.dispose()
        pytest.fail("RESQ_TEST_POSTGRES_URL must select PostgreSQL.")
    schema = f"resq_membership_test_{uuid4().hex}"
    metadata = MetaData(schema=schema)
    teams = Table("response_teams", metadata, Column("id", Integer, primary_key=True))
    users = Table("users", metadata, Column("id", Integer, primary_key=True),
                  Column("password_hash", String(255), nullable=False), Column("team_id", Integer))
    sessions = Table("token_sessions", metadata, Column("id", String(36), primary_key=True),
                     Column("user_id", ForeignKey(f"{schema}.users.id"), nullable=False))
    created = False
    try:
        with engine.begin() as connection:
            connection.execute(CreateSchema(schema))
            metadata.create_all(connection)
        created = True
        yield engine, schema, teams, users, sessions
    finally:
        # The exact random schema created above is the only cleanup target.
        if created:
            with engine.begin() as connection:
                connection.execute(DropSchema(schema, cascade=True, if_exists=True))
        engine.dispose()


def test_postgres_migration_preserves_accounts_sessions_and_is_idempotent(postgres_legacy_schema):
    engine, schema, teams, users, sessions = postgres_legacy_schema
    before = [(37, "synthetic-preserved-hash", 81), (38, "synthetic-citizen-hash", None)]
    session_id = "00000000-0000-0000-0000-000000000037"
    with engine.begin() as connection:
        connection.execute(teams.insert(), {"id": 81})
        connection.execute(users.insert(), [
            {"id": row[0], "password_hash": row[1], "team_id": row[2]} for row in before
        ])
        connection.execute(sessions.insert(), {"id": session_id, "user_id": 37})
    for _ in range(2):
        with engine.begin() as connection:
            ensure_user_team_foreign_key(connection, schema)
    with engine.connect() as connection:
        constraints = inspect(connection).get_foreign_keys("users", schema=schema)
        assert [item["name"] for item in constraints] == [USER_TEAM_CONSTRAINT]
        assert [tuple(row) for row in connection.execute(select(users).order_by(users.c.id))] == before
        assert connection.execute(select(sessions)).one() == (session_id, 37)
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(users.update().where(users.c.id == 37).values(team_id=999999))
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(teams.delete().where(teams.c.id == 81))


def test_postgres_migration_refuses_orphans_without_changing_records(postgres_legacy_schema):
    engine, schema, _teams, users, _sessions = postgres_legacy_schema
    with engine.begin() as connection:
        connection.execute(users.insert(), {"id": 37, "password_hash": "synthetic-preserved-hash", "team_id": 999999})
    with pytest.raises(RuntimeError, match="some accounts reference missing response teams"):
        with engine.begin() as connection:
            ensure_user_team_foreign_key(connection, schema)
    with engine.connect() as connection:
        assert inspect(connection).get_foreign_keys("users", schema=schema) == []
        assert connection.execute(select(users)).one() == (37, "synthetic-preserved-hash", 999999)
