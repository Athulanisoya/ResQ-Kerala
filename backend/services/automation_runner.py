"""Durable checks run independently; a failed job does not undo other jobs."""
import asyncio
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
import json
import logging

from sqlalchemy import text

from backend.models.automation import AutomationRuntime
from backend.services.automation_policy_service import get_policy


logger = logging.getLogger(__name__)


def run_cycle(session_factory=None, *, now=None):
    from backend.database.connection import SessionLocal
    from backend.services.alert_subscription_service import process_alert_subscriptions
    from backend.services.shelter_reminder_service import process_shelter_reminders
    from backend.services.shelter_waitlist_service import process_waitlists
    factory = session_factory or SessionLocal
    checked = now or datetime.now(timezone.utc)
    if checked.tzinfo is None:
        checked = checked.replace(tzinfo=timezone.utc)
    summary = {}
    jobs = {"area_alerts": lambda db: process_alert_subscriptions(db, now=checked),
            "shelter_reminders": lambda db: process_shelter_reminders(db, now=checked),
            "waitlists": lambda db: process_waitlists(db, now=checked, offer_minutes=get_policy(db).waitlist_offer_minutes)}
    # In particular, release the alert job's user locks before any shelter job.
    # A booking may hold a shelter lock while creating its notification.
    for name, operation in jobs.items():
        try:
            with factory() as db:
                if db.get_bind().dialect.name == "postgresql":
                    db.execute(text("SET LOCAL lock_timeout = '5s'"))
                    db.execute(text("SET LOCAL statement_timeout = '20s'"))
                    from backend.database.connection import Base
                    options = db.get_bind().get_execution_options()
                    schema = options.get("schema_translate_map", {}).get(Base.metadata.schema, Base.metadata.schema)
                    acquired = db.scalar(text("SELECT pg_try_advisory_xact_lock(hashtext(:key))"),
                                         {"key": "resq-automation:" + str(schema) + ":" + name})
                    if not acquired:
                        summary[name] = {"status": "already_running"}
                        continue
                result = operation(db)
                db.commit()
                summary[name] = {"status": "ok", **result}
        except Exception:
            # Driver/model exceptions can contain private data; never log inputs.
            logger.warning("Automation check failed: %s", name)
            summary[name] = {"status": "failed"}
    failed = any(item["status"] == "failed" for item in summary.values())
    with factory() as db:
        if db.get_bind().dialect.name == "postgresql":
            db.execute(text("SET LOCAL lock_timeout = '5s'"))
            db.execute(text("SET LOCAL statement_timeout = '20s'"))
            db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": "resq-automation:heartbeat"})
        state = db.get(AutomationRuntime, 1)
        if state is None:
            state = AutomationRuntime(id=1)
            db.add(state)
        state.checked_at = checked
        state.has_error = failed
        state.summary = json.dumps(summary, sort_keys=True)
        if all(item["status"] == "ok" for item in summary.values()):
            state.last_success_at = checked
        db.commit()
    return {"checked_at": checked.isoformat(), "has_error": failed, "jobs": summary}


async def _loop(settings):
    while True:
        try:
            await asyncio.to_thread(run_cycle)
        except Exception:
            logger.warning("Automation checks are temporarily unavailable")
        await asyncio.sleep(settings.automation_poll_seconds)


@asynccontextmanager
async def automation_lifespan(settings):
    # SQLite is restricted to tests; tests call the deterministic jobs directly.
    task = asyncio.create_task(_loop(settings)) if settings.automation_enabled and not settings.database_url.startswith("sqlite") else None
    try:
        yield
    finally:
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
