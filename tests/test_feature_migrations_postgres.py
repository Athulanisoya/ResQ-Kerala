"""Exercise feature-branch migrations against a disposable PostgreSQL schema."""
import os
from uuid import uuid4

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("ALLOW_SQLITE_FOR_TESTS", "true")
os.environ.setdefault("JWT_SECRET", "synthetic-feature-migration-test-secret-2026")

import pytest
from sqlalchemy import Column, Integer, MetaData, Table, create_engine, inspect, text
from sqlalchemy.schema import CreateSchema, DropSchema

from backend.database.feature_migrations import migrate_feature_tables
from backend.database.schema_compatibility import validate_feature_tables
from backend.models.shelter import Shelter, ShelterUpdate
from backend.models.relief import ReliefRequest as VidyaRequest, Inventory, Distribution
from backend.models.operations import ReliefRequest as OperationsRequest


@pytest.fixture
def legacy_db():
    url = os.environ.get("RESQ_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Set RESQ_TEST_POSTGRES_URL for isolated PostgreSQL feature migration checks.")
    engine = create_engine(url)
    if engine.dialect.name != "postgresql":
        pytest.fail("RESQ_TEST_POSTGRES_URL must select PostgreSQL")
    schema = "resq_feature_test_" + uuid4().hex
    metadata = MetaData(schema=schema)
    for name in ("users", "response_teams", "incident_reports"):
        Table(name, metadata, Column("id", Integer, primary_key=True))
    for model in (Shelter, ShelterUpdate, VidyaRequest, Inventory, Distribution, OperationsRequest):
        model.__table__.to_metadata(metadata)
    created = False
    try:
        with engine.begin() as connection:
            connection.execute(CreateSchema(schema))
            for name in ("users", "response_teams", "incident_reports"):
                metadata.tables[f"{schema}.{name}"].create(connection)
                connection.execute(text(f'INSERT INTO "{schema}"."{name}" (id) VALUES (1)'))
        created = True
        yield engine, schema, metadata
    finally:
        if created:
            with engine.begin() as connection:
                connection.execute(DropSchema(schema, cascade=True, if_exists=True))
        engine.dispose()


def setup_shelter(connection, schema, branch):
    s = f'"{schema}"'
    if branch == "arya":
        connection.execute(text(f'''CREATE TABLE {s}.shelters (
            id SERIAL PRIMARY KEY, name VARCHAR(160) NOT NULL, district VARCHAR(100) NOT NULL,
            locality VARCHAR(120) NOT NULL, address VARCHAR(300) NOT NULL,
            capacity INTEGER NOT NULL CHECK (capacity >= 0), occupied INTEGER NOT NULL CHECK (occupied >= 0),
            status VARCHAR(10) NOT NULL CHECK (status IN ('OPEN','FULL','CLOSED')),
            contact VARCHAR(60), source_name VARCHAR(200) NOT NULL, updated_at TIMESTAMPTZ NOT NULL,
            CHECK (occupied <= capacity))'''))
        connection.execute(text(f'''INSERT INTO {s}.shelters
            (name,district,locality,address,capacity,occupied,status,source_name,updated_at)
            VALUES ('Arya','Kochi','Centre','Road',20,4,'OPEN','demo',CURRENT_TIMESTAMP)'''))
    else:
        connection.execute(text(f'''CREATE TABLE {s}.shelters (
            id SERIAL PRIMARY KEY, name VARCHAR(100) NOT NULL, location VARCHAR(255) NOT NULL,
            capacity INTEGER NOT NULL, occupied INTEGER NOT NULL, team_id INTEGER NOT NULL REFERENCES {s}.response_teams(id),
            version INTEGER NOT NULL, CHECK (capacity > 0 AND occupied >= 0 AND occupied <= capacity))'''))
        connection.execute(text(f'''INSERT INTO {s}.shelters (name,location,capacity,occupied,team_id,version)
            VALUES ('Vidya','Harbour',20,20,1,2)'''))
        connection.execute(text(f'''CREATE TABLE {s}.shelter_updates (
            id SERIAL PRIMARY KEY, shelter_id INTEGER NOT NULL REFERENCES {s}.shelters(id),
            capacity INTEGER NOT NULL, occupied INTEGER NOT NULL, version INTEGER NOT NULL,
            note VARCHAR(1000) NOT NULL, changed_by INTEGER NOT NULL REFERENCES {s}.users(id),
            created_at TIMESTAMP NOT NULL)'''))
        connection.execute(text(f'''INSERT INTO {s}.shelter_updates
            (shelter_id,capacity,occupied,version,note,changed_by,created_at)
            VALUES (1,20,20,2,'preserved',1,CURRENT_TIMESTAMP)'''))


@pytest.mark.parametrize("branch", ["arya", "vidya"])
def test_known_shelters_preserve_rows_and_support_both_workflows(legacy_db, branch):
    engine, schema, metadata = legacy_db
    s = f'"{schema}"'
    with engine.begin() as connection:
        setup_shelter(connection, schema, branch)
    for _ in range(2):
        with engine.begin() as connection:
            migrate_feature_tables(connection, metadata)
            validate_feature_tables(connection, metadata)
            metadata.create_all(connection)
    with engine.begin() as connection:
        row = connection.execute(text(f'SELECT name, capacity, occupied, status, version FROM {s}.shelters WHERE id=1')).one()
        assert tuple(row) == (("Arya", 20, 4, "OPEN", 1) if branch == "arya" else ("Vidya", 20, 20, "FULL", 2))
        connection.execute(text(f'''INSERT INTO {s}.shelters (name,location,capacity,occupied,status,team_id,version)
            VALUES ('new managed','Station',1,0,'OPEN',1,1)'''))
        connection.execute(text(f'''INSERT INTO {s}.shelters (name,district,locality,address,capacity,occupied,status,source_name,version)
            VALUES ('new public','Kochi','Centre','Road',0,0,'FULL','demo',1)'''))
        if branch == "vidya":
            assert connection.scalar(text(f'SELECT note FROM {s}.shelter_updates WHERE shelter_id=1')) == "preserved"


def test_vidya_relief_rename_preserves_distribution_fk_and_sequences(legacy_db):
    engine, schema, metadata = legacy_db
    s = f'"{schema}"'
    with engine.begin() as connection:
        connection.execute(text(f'''CREATE TABLE {s}.relief_requests (
            id SERIAL PRIMARY KEY, incident_id INTEGER NOT NULL REFERENCES {s}.incident_reports(id),
            item VARCHAR(20) NOT NULL, quantity INTEGER NOT NULL, fulfilled INTEGER NOT NULL,
            created_by INTEGER NOT NULL REFERENCES {s}.users(id), created_at TIMESTAMP NOT NULL,
            CONSTRAINT uq_relief_incident_item UNIQUE (incident_id,item),
            CHECK (quantity > 0 AND fulfilled >= 0 AND fulfilled <= quantity))'''))
        connection.execute(text(f'CREATE INDEX ix_relief_requests_incident_id ON {s}.relief_requests (incident_id)'))
        connection.execute(text(f'''INSERT INTO {s}.relief_requests (incident_id,item,quantity,fulfilled,created_by,created_at)
            VALUES (1,'food',5,2,1,CURRENT_TIMESTAMP)'''))
        metadata.tables[f"{schema}.relief_inventory"].create(connection)
        connection.execute(text(f"INSERT INTO {s}.relief_inventory (id,item,quantity) VALUES (1,'food',3)"))
        connection.execute(text(f'''CREATE TABLE {s}.relief_distributions (
            id SERIAL PRIMARY KEY, request_id INTEGER NOT NULL REFERENCES {s}.relief_requests(id),
            inventory_id INTEGER NOT NULL REFERENCES {s}.relief_inventory(id),
            team_id INTEGER NOT NULL REFERENCES {s}.response_teams(id),
            recorded_by INTEGER NOT NULL REFERENCES {s}.users(id), quantity INTEGER NOT NULL CHECK (quantity > 0),
            idempotency_key VARCHAR(36) NOT NULL UNIQUE, created_at TIMESTAMP NOT NULL)'''))
        connection.execute(text(f'''INSERT INTO {s}.relief_distributions
            (request_id,inventory_id,team_id,recorded_by,quantity,idempotency_key,created_at)
            VALUES (1,1,1,1,2,'old-key',CURRENT_TIMESTAMP)'''))
    for _ in range(2):
        with engine.begin() as connection:
            migrate_feature_tables(connection, metadata)
            validate_feature_tables(connection, metadata)
            metadata.create_all(connection)
    with engine.begin() as connection:
        assert tuple(connection.execute(text(f'SELECT item,quantity,fulfilled FROM {s}.vidya_relief_requests WHERE id=1')).one()) == ('food',5,2)
        assert connection.scalar(text(f'SELECT request_id FROM {s}.relief_distributions WHERE idempotency_key=\'old-key\'')) == 1
        fks = inspect(connection).get_foreign_keys('relief_distributions', schema=schema)
        assert any(fk['constrained_columns'] == ['request_id'] and fk['referred_table'] == 'vidya_relief_requests' for fk in fks)
        new_id = connection.scalar(text(f'''INSERT INTO {s}.vidya_relief_requests
            (incident_id,item,quantity,fulfilled,created_by,created_at) VALUES (1,'water',1,0,1,CURRENT_TIMESTAMP) RETURNING id'''))
        assert new_id == 2
        ops_id = connection.scalar(text(f'''INSERT INTO {s}.relief_requests
            (incident_id,created_by_user_id,kind,status,created_at) VALUES (1,1,'SUPPLIES','PENDING',CURRENT_TIMESTAMP) RETURNING id'''))
        assert ops_id == 1


def test_unknown_layout_rejects_and_rolls_back_prior_upgrade(legacy_db):
    engine, schema, metadata = legacy_db
    s = f'"{schema}"'
    with engine.begin() as connection:
        setup_shelter(connection, schema, "arya")
        connection.execute(text(f'CREATE TABLE {s}.relief_requests (id SERIAL PRIMARY KEY, mystery TEXT NOT NULL)'))
    with pytest.raises(RuntimeError, match="incompatible"):
        with engine.begin() as connection:
            migrate_feature_tables(connection, metadata)
            validate_feature_tables(connection, metadata)
    with engine.connect() as connection:
        assert "version" not in {c['name'] for c in inspect(connection).get_columns('shelters', schema=schema)}
        assert connection.scalar(text(f'SELECT name FROM {s}.shelters')) == 'Arya'


def test_wrong_distribution_foreign_key_rejected(legacy_db):
    engine, schema, metadata = legacy_db
    s = f'"{schema}"'
    with engine.begin() as connection:
        metadata.create_all(connection)
        fk = next(fk for fk in inspect(connection).get_foreign_keys('relief_distributions', schema=schema)
                  if fk['constrained_columns'] == ['request_id'])
        connection.execute(text(f'ALTER TABLE {s}.relief_distributions DROP CONSTRAINT "{fk["name"]}"'))
        connection.execute(text(f'ALTER TABLE {s}.relief_distributions ADD CONSTRAINT wrong_request_fk '
                                f'FOREIGN KEY (request_id) REFERENCES {s}.relief_requests(id)'))
        with pytest.raises(RuntimeError, match="request_id has an incompatible foreign key"):
            validate_feature_tables(connection, metadata)
