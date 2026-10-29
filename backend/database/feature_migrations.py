"""Conservative PostgreSQL upgrades for the two known feature-branch schemas."""

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.schema import MetaData


_ARYA_SHELTER = frozenset({
    "id", "name", "district", "locality", "address", "capacity", "occupied",
    "status", "contact", "source_name", "updated_at",
})
_VIDYA_SHELTER = frozenset({
    "id", "name", "location", "capacity", "occupied", "team_id", "version",
})
_VIDYA_RELIEF = frozenset({
    "id", "incident_id", "item", "quantity", "fulfilled", "created_by", "created_at",
})


def migrate_feature_tables(connection: Connection, metadata: MetaData) -> None:
    """Upgrade known PostgreSQL branch layouts in the caller's transaction.

    Unknown or partially migrated layouts are left for the compatibility guard
    to reject. SQLite is test-only and legacy table rebuilds are not attempted.
    All changes roll back if migration or subsequent validation fails.
    """
    if connection.dialect.name != "postgresql":
        return
    schema = metadata.schema
    if not schema:
        raise RuntimeError("A schema is required for PostgreSQL feature migrations")
    quote = connection.dialect.identifier_preparer.quote
    def table(name):
        return f"{quote(schema)}.{quote(name)}"

    # Serialize this migration and metadata creation across application starts.
    connection.execute(text("SET LOCAL lock_timeout = '10s'"))
    connection.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
                       {"key": "resq-feature-schema:" + schema})
    inspector = inspect(connection)
    if inspector.has_table("shelters", schema=schema):
        columns = frozenset(c["name"] for c in inspector.get_columns("shelters", schema=schema))
        shelter = table("shelters")
        if columns == _ARYA_SHELTER:
            connection.execute(text(f"LOCK TABLE {shelter} IN ACCESS EXCLUSIVE MODE"))
            if frozenset(c["name"] for c in inspect(connection).get_columns("shelters", schema=schema)) != columns:
                raise RuntimeError("Shelter schema changed while acquiring the migration lock.")
            for name in ("district", "locality", "address", "source_name", "updated_at"):
                connection.execute(text(f"ALTER TABLE {shelter} ALTER COLUMN {quote(name)} DROP NOT NULL"))
            connection.execute(text(f"ALTER TABLE {shelter} ADD COLUMN location VARCHAR(255)"))
            connection.execute(text(f"ALTER TABLE {shelter} ADD COLUMN team_id INTEGER REFERENCES {table('response_teams')}(id)"))
            connection.execute(text(f"ALTER TABLE {shelter} ADD COLUMN version INTEGER NOT NULL DEFAULT 1"))
        elif columns == _VIDYA_SHELTER:
            connection.execute(text(f"LOCK TABLE {shelter} IN ACCESS EXCLUSIVE MODE"))
            if frozenset(c["name"] for c in inspect(connection).get_columns("shelters", schema=schema)) != columns:
                raise RuntimeError("Shelter schema changed while acquiring the migration lock.")
            # Replace only the exact old count check. Retaining it would reject
            # zero-capacity shelters that the combined API explicitly permits.
            checks = inspect(connection).get_check_constraints("shelters", schema=schema)
            normalized = lambda value: "".join(c for c in value.lower() if c not in " ()\t\n\r")
            matching = [check for check in checks if normalized(check["sqltext"]) ==
                        "capacity>0andoccupied>=0andoccupied<=capacity"]
            if len(matching) != 1 or not matching[0]["name"]:
                raise RuntimeError("Cannot safely identify the legacy shelter capacity constraint.")
            connection.execute(text(f"ALTER TABLE {shelter} DROP CONSTRAINT {quote(matching[0]['name'])}"))
            connection.execute(text(f"ALTER TABLE {shelter} ADD CONSTRAINT ck_shelter_counts CHECK (capacity >= 0 AND occupied >= 0 AND occupied <= capacity)"))
            connection.execute(text(f"ALTER TABLE {shelter} ALTER COLUMN name TYPE VARCHAR(160)"))
            for name in ("location", "team_id"):
                connection.execute(text(f"ALTER TABLE {shelter} ALTER COLUMN {quote(name)} DROP NOT NULL"))
            for name, length in (("district", 100), ("locality", 120), ("address", 300),
                                 ("contact", 60), ("source_name", 200)):
                connection.execute(text(f"ALTER TABLE {shelter} ADD COLUMN {quote(name)} VARCHAR({length})"))
            connection.execute(text(f"ALTER TABLE {shelter} ADD COLUMN status VARCHAR(10)"))
            connection.execute(text(f"UPDATE {shelter} SET status = CASE WHEN occupied >= capacity THEN 'FULL' ELSE 'OPEN' END"))
            connection.execute(text(f"ALTER TABLE {shelter} ALTER COLUMN status SET NOT NULL"))
            connection.execute(text(f"ALTER TABLE {shelter} ADD CONSTRAINT ck_shelter_status CHECK (status IN ('OPEN', 'FULL', 'CLOSED'))"))
            connection.execute(text(f"ALTER TABLE {shelter} ADD COLUMN updated_at TIMESTAMP WITH TIME ZONE"))
            for index, columns_sql in (("ix_shelters_district", "district"),
                                       ("ix_shelters_locality", "locality"),
                                       ("ix_shelters_district_status", "district, status")):
                connection.execute(text(f"CREATE INDEX {quote(index)} ON {shelter} ({columns_sql})"))

    inspector = inspect(connection)
    if not inspector.has_table("relief_requests", schema=schema):
        return
    columns = frozenset(c["name"] for c in inspector.get_columns("relief_requests", schema=schema))
    if columns != _VIDYA_RELIEF:
        return
    if inspector.has_table("vidya_relief_requests", schema=schema):
        raise RuntimeError("Both legacy and new Vidya relief request tables exist; resolve them manually before starting.")
    original = table("relief_requests")
    connection.execute(text(f"LOCK TABLE {original} IN ACCESS EXCLUSIVE MODE"))
    if frozenset(c["name"] for c in inspect(connection).get_columns("relief_requests", schema=schema)) != columns:
        raise RuntimeError("Relief schema changed while acquiring the migration lock.")

    # Move the serial sequence and indexes that would collide with Athul's new
    # relief_requests table. PostgreSQL updates referencing foreign keys on a
    # table rename and preserves the sequence ownership and next value.
    renames = [("relief_requests_pkey", "vidya_relief_requests_pkey"),
               ("ix_relief_requests_incident_id", "ix_vidya_relief_requests_incident_id"),
               ("relief_requests_id_seq", "vidya_relief_requests_id_seq")]
    for old, new in renames:
        found = connection.scalar(text("SELECT to_regclass(:name)"), {"name": table(old)})
        if found is not None:
            if old.endswith("_seq"):
                owned = connection.scalar(text(
                    "SELECT to_regclass(pg_get_serial_sequence(:table_name, 'id')) = to_regclass(:object_name)"
                ), {"table_name": original, "object_name": table(old)})
                kind = "SEQUENCE"
            else:
                owned = connection.scalar(text(
                    "SELECT indrelid = to_regclass(:table_name) FROM pg_index WHERE indexrelid = to_regclass(:object_name)"
                ), {"table_name": original, "object_name": table(old)})
                kind = "INDEX"
            if owned is not True:
                raise RuntimeError(f"Cannot migrate relief requests: {old} is not owned by the legacy table.")
            if connection.scalar(text("SELECT to_regclass(:name)"), {"name": table(new)}) is not None:
                raise RuntimeError(f"Cannot migrate relief requests: {new} already exists.")
            connection.execute(text(f"ALTER {kind} {table(old)} RENAME TO {quote(new)}"))
    connection.execute(text(f"ALTER TABLE {original} RENAME TO {quote('vidya_relief_requests')}"))
