import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, text

from backend.database.schema_compatibility import validate_feature_tables


def expected_metadata():
    metadata = MetaData()
    Table(
        "shelters", metadata,
        Column("id", Integer, primary_key=True),
        Column("name", String, nullable=False),
        Column("location", String, nullable=True),
        Column("version", Integer, nullable=False),
    )
    Table(
        "relief_requests", metadata,
        Column("id", Integer, primary_key=True),
        Column("incident_id", Integer, nullable=False),
        Column("kind", String, nullable=False),
    )
    return metadata


def test_fresh_and_compatible_tables_pass():
    engine = create_engine("sqlite://")
    metadata = expected_metadata()
    with engine.begin() as connection:
        validate_feature_tables(connection, metadata)
        metadata.create_all(connection)
        validate_feature_tables(connection, metadata)


def test_legacy_layouts_are_rejected_without_modifying_data():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE shelters (id INTEGER PRIMARY KEY, name TEXT NOT NULL)"))
        connection.execute(text("INSERT INTO shelters (id, name) VALUES (1, 'existing shelter')"))
        connection.execute(text("CREATE TABLE relief_requests (id INTEGER PRIMARY KEY, incident_id INTEGER NOT NULL, item TEXT NOT NULL)"))
        with pytest.raises(RuntimeError, match="migrate its schema and data") as error:
            validate_feature_tables(connection, expected_metadata())
        assert "shelters: missing columns location, version" in str(error.value)
        assert "relief_requests: missing columns kind" in str(error.value)
        assert "relief_requests: extra required columns item" in str(error.value)
        assert connection.scalar(text("SELECT name FROM shelters WHERE id = 1")) == "existing shelter"


def test_rejects_legacy_not_null_constraint_on_optional_field():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE shelters (id INTEGER PRIMARY KEY, name TEXT NOT NULL, "
            "location TEXT NOT NULL DEFAULT '', version INTEGER NOT NULL)"
        ))
        with pytest.raises(RuntimeError, match="shelters: unexpectedly NOT NULL columns location"):
            validate_feature_tables(connection, expected_metadata())


def test_extra_nullable_or_defaulted_column_is_accepted():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE shelters (id INTEGER PRIMARY KEY, name TEXT NOT NULL, "
            "location TEXT, version INTEGER NOT NULL, old_note TEXT, "
            "legacy_flag INTEGER NOT NULL DEFAULT 0)"
        ))
        validate_feature_tables(connection, expected_metadata())
