"""Fail safely when an earlier feature branch left incompatible tables behind."""

from sqlalchemy import inspect
from sqlalchemy.engine import Connection
from sqlalchemy.schema import MetaData


_FEATURE_TABLES = {
    "shelters",
    "shelter_updates",
    "relief_requests",
    "vidya_relief_requests",
    "relief_inventory",
    "relief_distributions",
    "operations_relief_requests",
}


def validate_feature_tables(connection: Connection, metadata: MetaData) -> None:
    """Reject legacy layouts before create_all can leave them silently unchanged.

    This is a compatibility guard, not a schema migration. It deliberately does
    not change or remove existing data, and cannot establish full compatibility
    of constraints, types, or application semantics.
    """
    inspector = inspect(connection)
    problems = []
    for table in metadata.sorted_tables:
        if table.name not in _FEATURE_TABLES:
            continue
        if not inspector.has_table(table.name, schema=table.schema):
            continue

        existing = {
            column["name"]: column
            for column in inspector.get_columns(table.name, schema=table.schema)
        }
        expected = {column.name: column for column in table.columns}
        missing = sorted(expected.keys() - existing.keys())
        if missing:
            problems.append(f"{table.name}: missing columns {', '.join(missing)}")

        # ORM writes may supply NULL for model-optional columns. A stricter
        # legacy table would reject those writes even if it has a default.
        restricted = sorted(
            name for name in expected.keys() & existing.keys()
            if expected[name].nullable and not existing[name].get("nullable", True)
        )
        if restricted:
            problems.append(f"{table.name}: unexpectedly NOT NULL columns {', '.join(restricted)}")

        # An old required column unknown to the model can also reject inserts.
        extra_required = sorted(
            name for name in existing.keys() - expected.keys()
            if not existing[name].get("nullable", True)
            and existing[name].get("default") is None
            and not existing[name].get("primary_key")
            and not existing[name].get("identity")
            and not existing[name].get("computed")
        )
        if extra_required:
            problems.append(f"{table.name}: extra required columns {', '.join(extra_required)}")

        # A prior table rename can leave a valid-looking distribution table
        # pointing to the wrong relief ledger. Column names alone cannot prove
        # that its history still refers to the intended request table.
        if table.name == "relief_distributions" and "request_id" in expected:
            fk_options = {"postgresql_ignore_search_path": True} if connection.dialect.name == "postgresql" else {}
            fks = inspector.get_foreign_keys(table.name, schema=table.schema, **fk_options)
            if not any(fk["constrained_columns"] == ["request_id"]
                       and fk["referred_table"] == "vidya_relief_requests"
                       and fk["referred_columns"] == ["id"]
                       and fk["referred_schema"] == table.schema for fk in fks):
                problems.append("relief_distributions: request_id has an incompatible foreign key")

    if problems:
        raise RuntimeError(
            "Existing shelter or relief tables are incompatible with this version: "
            + "; ".join(problems)
            + ". Back up the database and migrate its schema and data before starting. "
            "No existing data was changed by this compatibility check."
        )
