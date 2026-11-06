from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from fastapi import HTTPException
from test_operations_postgres import pg_ops
from backend.models import User
from backend.services.preparedness_service import PlanInput, REVISION, save, read

def test_plan_competing_saves_never_overwrite_newer_version(pg_ops):
    pg = pg_ops; barrier = Barrier(3)
    def update(index):
        with pg.sessions() as db:
            barrier.wait(timeout=10)
            try:
                save(db, db.get(User, pg.users['citizen']), PlanInput(expected_version=0,
                    guidance_revision=REVISION, nearby_meeting=f'Synthetic private point {index}'))
                return 200
            except HTTPException as error:
                db.rollback(); return error.status_code
    with ThreadPoolExecutor(max_workers=3) as pool:
        jobs = [pool.submit(update, i) for i in range(3)]
        assert sorted(job.result(timeout=30) for job in jobs) == [200, 409, 409]
    with pg.sessions() as db:
        assert read(db, db.get(User, pg.users['citizen']))['version'] == 1
        assert read(db, db.get(User, pg.users['admin']))['version'] == 0
