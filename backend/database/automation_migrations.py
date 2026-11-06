"""Additive upgrades preserve incident notifications and shelter audit history."""
from sqlalchemy import inspect, text


def migrate_automations(connection, metadata):
    schema = metadata.schema
    quote = connection.dialect.identifier_preparer.quote
    def table(name):
        return f"{quote(schema)}.{quote(name)}" if schema else quote(name)
    inspector = inspect(connection)
    def columns(name):
        return {c["name"]: c for c in inspector.get_columns(name, schema=schema)} if inspector.has_table(name, schema=schema) else {}
    notifications = columns("incident_notifications")
    if notifications:
        if "target_url" not in notifications:
            connection.execute(text(f"ALTER TABLE {table('incident_notifications')} ADD COLUMN target_url VARCHAR(600)"))
        if connection.dialect.name == "postgresql" and not notifications["incident_id"]["nullable"]:
            connection.execute(text(f"ALTER TABLE {table('incident_notifications')} ALTER COLUMN incident_id DROP NOT NULL"))
    shelters = columns("shelters")
    if shelters and "capacity_confirmed_at" not in shelters:
        dtype = "TIMESTAMP WITH TIME ZONE" if connection.dialect.name == "postgresql" else "DATETIME"
        connection.execute(text(f"ALTER TABLE {table('shelters')} ADD COLUMN capacity_confirmed_at {dtype}"))
        # Only attributed staff snapshots can establish a historical confirmation.
        if connection.dialect.name == "postgresql" and columns("shelter_updates") and columns("users"):
            connection.execute(text(f"""UPDATE {table('shelters')} s SET capacity_confirmed_at =
                (SELECT MAX(su.created_at AT TIME ZONE 'UTC') FROM {table('shelter_updates')} su
                 JOIN {table('users')} u ON u.id = su.changed_by
                 WHERE su.shelter_id = s.id AND u.role IN ('admin','response_team')
                 AND su.note NOT LIKE 'Registration #%'
                 AND su.note NOT LIKE 'Waitlist #%')"""))
    snapshots = columns("shelter_updates")
    if connection.dialect.name == "postgresql" and snapshots and not snapshots["changed_by"]["nullable"]:
        connection.execute(text(f"ALTER TABLE {table('shelter_updates')} ALTER COLUMN changed_by DROP NOT NULL"))
