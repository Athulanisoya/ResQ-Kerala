"""Add retry-safe report keys without rewriting existing incident records."""

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.schema import MetaData


def migrate_offline_reports(connection: Connection, metadata: MetaData) -> None:
    schema = metadata.schema
    if connection.dialect.name == "postgresql":
        connection.execute(text("SET LOCAL lock_timeout = '10s'"))
        connection.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
                           {"key": "resq-offline-report-schema:" + (schema or "public")})
    inspector = inspect(connection)
    if not inspector.has_table("incident_reports", schema=schema):
        return
    quote = connection.dialect.identifier_preparer.quote
    table = f"{quote(schema)}.{quote('incident_reports')}" if schema else quote("incident_reports")
    columns = {column["name"] for column in inspector.get_columns("incident_reports", schema=schema)}
    for name, length in (("client_submission_id", 36), ("submission_fingerprint", 64)):
        if name not in columns:
            connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {quote(name)} VARCHAR({length})"))
    keys = {tuple(key["column_names"]) for key in inspect(connection).get_unique_constraints("incident_reports", schema=schema)}
    indexes = {tuple(index["column_names"]) for index in inspect(connection).get_indexes("incident_reports", schema=schema) if index.get("unique")}
    if ("user_id", "client_submission_id") not in keys | indexes:
        connection.execute(text(f"CREATE UNIQUE INDEX {quote('uq_incident_user_client_submission')} ON {table} (user_id, client_submission_id)"))
