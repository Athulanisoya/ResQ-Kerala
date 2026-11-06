from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from fastapi import HTTPException
from sqlalchemy import select, func
from test_operations_postgres import pg_ops
from backend.models import Shelter, User
from backend.models.shelter_facilities import ShelterFacilitiesEvent
from backend.services.shelter_facilities_service import update, FacilitiesInput, LABELS

def test_competing_facility_confirmations_reject_stale_version(pg_ops):
    pg = pg_ops
    with pg.sessions() as db:
        row = Shelter(name='Synthetic PG facilities', location='Aluva', capacity=20, occupied=3)
        db.add(row); db.commit(); shelter_id = row.id
    barrier = Barrier(3)
    def save():
        with pg.sessions() as db:
            barrier.wait(timeout=10)
            try:
                update(db, shelter_id, db.get(User, pg.users['admin']), FacilitiesInput(
                    expected_version=0, confirmed=True, note='Synthetic facility inspection', **{key: 'YES' for key in LABELS}))
                return 200
            except HTTPException as error:
                db.rollback(); return error.status_code
    with ThreadPoolExecutor(max_workers=3) as pool:
        jobs = [pool.submit(save) for _ in range(3)]
        assert sorted(job.result(timeout=30) for job in jobs) == [200, 409, 409]
    with pg.sessions() as db:
        assert db.scalar(select(func.count()).select_from(ShelterFacilitiesEvent)) == 1
        row = db.get(Shelter, shelter_id)
        assert row.occupied == 3 and row.capacity == 20 and row.version == 1
