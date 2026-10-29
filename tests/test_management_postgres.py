"""Concurrent administrator changes use isolated PostgreSQL schemas."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from fastapi import HTTPException
from sqlalchemy import select
from backend.models import Role, User
from backend.routers.management import UserChange, change_user
from test_operations_postgres import pg_ops


def test_concurrent_admin_deactivations_cannot_remove_all_admins(pg_ops):
    with pg_ops.sessions() as db:
        second = User(full_name="Second synthetic admin", email="second-pg-admin@example.com",
                      password_hash="synthetic-unused-hash", role=Role.ADMIN, active=True)
        db.add(second); db.commit(); second_id = second.id
    first_id = pg_ops.users["admin"]
    barrier = Barrier(2)
    def deactivate(actor_id, target_id):
        with pg_ops.sessions() as db:
            actor = db.get(User, actor_id)
            barrier.wait(timeout=10)
            try:
                change_user(target_id, UserChange(role=Role.ADMIN, team_id=None, active=False), db, actor)
                return 200
            except HTTPException as exc:
                db.rollback()
                return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(deactivate, first_id, second_id)
        second = pool.submit(deactivate, second_id, first_id)
        statuses = sorted([first.result(timeout=30), second.result(timeout=30)])
    assert statuses == [200, 403]
    with pg_ops.sessions() as db:
        active = list(db.scalars(select(User.id).where(User.role == Role.ADMIN, User.active.is_(True))))
        assert len(active) == 1
