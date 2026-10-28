"""Small, data-preserving upgrades for the existing Week 1 schema."""
from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection


USER_TEAM_CONSTRAINT = "fk_users_team_id_response_teams"


def ensure_user_team_foreign_key(connection: Connection, schema: str) -> None:
    """Enforce existing memberships without recreating tables or changing records.

    PostgreSQL ``create_all`` leaves existing tables untouched. Serialize this
    upgrade with account/team writes and other startups, then validate every
    existing membership before adding (or validating) the foreign key.
    """
    if connection.dialect.name != "postgresql":
        return

    quote = connection.dialect.identifier_preparer.quote
    users = f"{quote(schema)}.{quote('users')}"
    teams = f"{quote(schema)}.{quote('response_teams')}"
    connection.execute(text("SET LOCAL lock_timeout = '10s'"))
    connection.execute(text(f"LOCK TABLE {teams}, {users} IN SHARE ROW EXCLUSIVE MODE"))

    has_orphans = connection.scalar(text(
        f"SELECT EXISTS (SELECT 1 FROM {users} AS account "
        f"LEFT JOIN {teams} AS team ON account.team_id = team.id "
        "WHERE account.team_id IS NOT NULL AND team.id IS NULL)"
    ))
    if has_orphans:
        raise RuntimeError(
            "Cannot enforce team membership integrity: some accounts reference missing response teams. "
            "Correct those memberships before restarting. No account or team records were changed."
        )

    constraints = inspect(connection).get_foreign_keys(
        "users", schema=schema, postgresql_ignore_search_path=True
    )
    for constraint in constraints:
        if (constraint["constrained_columns"] == ["team_id"]
                and constraint["referred_table"] == "response_teams"
                and constraint["referred_columns"] == ["id"]
                and constraint["referred_schema"] == schema):
            connection.execute(text(
                f"ALTER TABLE {users} VALIDATE CONSTRAINT {quote(constraint['name'])}"
            ))
            return

    if any(constraint["name"] == USER_TEAM_CONSTRAINT for constraint in constraints):
        raise RuntimeError("The team membership constraint exists with an unexpected definition.")
    connection.execute(text(
        f"ALTER TABLE {users} ADD CONSTRAINT {quote(USER_TEAM_CONSTRAINT)} "
        f"FOREIGN KEY (team_id) REFERENCES {teams} (id)"
    ))

def migrate_incident_summaries(
    connection: Connection,
    schema: str | None = None,
) -> None:
    """
    Move existing incident summaries into report_analysis.

    Preserve original incident records and avoid duplicate
    analysis records when initialization runs repeatedly.
    """
    if connection.dialect.name not in {"postgresql", "sqlite"}:
        return

    inspector = inspect(connection)

    if connection.dialect.name == "postgresql":
        if not schema:
            raise RuntimeError(
                "A database schema is required for PostgreSQL."
            )

        incident_table = (
            f"{connection.dialect.identifier_preparer.quote(schema)}."
            f"{connection.dialect.identifier_preparer.quote('incident_reports')}"
        )

        analysis_table = (
            f"{connection.dialect.identifier_preparer.quote(schema)}."
            f"{connection.dialect.identifier_preparer.quote('report_analysis')}"
        )

        incident_columns = {
            column["name"]
            for column in inspector.get_columns(
                "incident_reports",
                schema=schema,
            )
        }

    else:
        incident_table = "incident_reports"
        analysis_table = "report_analysis"

        incident_columns = {
            column["name"]
            for column in inspector.get_columns("incident_reports")
        }

    # Existing databases may not have these columns.
    required_columns = {
        "summary",
        "summary_is_provisional",
        "requires_manual_review",
    }

    if not required_columns.issubset(incident_columns):
        return

    connection.execute(
        text(
            f"""
            INSERT INTO {analysis_table} (
                incident_id,
                summary,
                summary_is_provisional,
                requires_manual_review,
                created_at
            )
            SELECT
                incident.id,
                incident.summary,
                COALESCE(incident.summary_is_provisional, TRUE),
                COALESCE(incident.requires_manual_review, TRUE),
                CURRENT_TIMESTAMP
            FROM {incident_table} AS incident
            WHERE incident.summary IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1
                  FROM {analysis_table} AS analysis
                  WHERE analysis.incident_id = incident.id
                    AND analysis.summary = incident.summary
              )
            """
        )
    )
