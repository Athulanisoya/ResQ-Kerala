"""PostgreSQL cross-API acceptance must not duplicate task history."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from fastapi import HTTPException
from sqlalchemy import select
from test_operations_postgres import pg_ops
from backend.models import User
from backend.models.operations import IncidentTask, IncidentTaskEvent
from backend.schemas.operations_schema import TaskNote
from backend.services import operations_service, response_service


def test_legacy_and_operations_acceptance_race_keeps_one_event(pg_ops):
    pg_ops.assign()
    barrier = Barrier(2)
    def execute(style):
        with pg_ops.sessions() as db:
            user = db.get(User, pg_ops.users['rescue'])
            barrier.wait(timeout=10)
            try:
                if style == 'legacy':
                    response_service.accept_task(db, pg_ops.incidents[0], user)
                else:
                    operations_service.accept_task(db, user, pg_ops.incidents[0], TaskNote())
                return 200
            except HTTPException as exc:
                db.rollback(); return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(execute, 'legacy'); b = pool.submit(execute, 'operations')
        statuses = sorted([a.result(timeout=30), b.result(timeout=30)])
        assert statuses in ([200, 200], [200, 409])
    with pg_ops.sessions() as db:
        tasks = list(db.scalars(select(IncidentTask).where(IncidentTask.incident_id == pg_ops.incidents[0])))
        assert len(tasks) == 1 and tasks[0].accepted_at is not None
        events = list(db.scalars(select(IncidentTaskEvent.status).where(IncidentTaskEvent.task_id == tasks[0].id)))
        assert len([status for status in events if status in {'ACCEPTED','TASK_ACCEPTED'}]) == 1
