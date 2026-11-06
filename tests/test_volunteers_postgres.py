from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

from fastapi import HTTPException
from test_operations_postgres import pg_ops
from backend.models import User
from backend.schemas.volunteer_schema import VolunteerInput, ApplicationReview, ShiftCreate, ShiftSignup
from backend.services import volunteer_service as service


def setup(pg):
    for name in ('citizen', 'citizen2'):
        with pg.sessions() as db:
            app = service.save_application(db, db.get(User, pg.users[name]), VolunteerInput(
                expected_version=0, district_id='ernakulam', ward='Synthetic ward', skills=['logistics'],
                availability='Weekend mornings', consent=True))['application']
        with pg.sessions() as db:
            service.review_application(db, db.get(User, pg.users['admin']), app['id'], ApplicationReview(
                expected_version=1, decision='APPROVED', note='Synthetic approval'))
    start = datetime.now(timezone.utc) + timedelta(days=2)
    with pg.sessions() as db:
        return service.create_shift(db, db.get(User, pg.users['admin']), ShiftCreate(
            title='Synthetic one place', kind='FIELD_SUPPORT', place_id='ernakulam', slots=1,
            starts_at=start, ends_at=start+timedelta(hours=1)))


def test_competing_volunteers_cannot_overfill_shift(pg_ops):
    pg = pg_ops
    shift = setup(pg)
    barrier = Barrier(2)
    def join(name):
        with pg.sessions() as db:
            barrier.wait(timeout=10)
            try:
                service.join_shift(db, db.get(User, pg.users[name]), shift['id'], ShiftSignup(expected_version=1))
                return 200
            except HTTPException as error:
                db.rollback()
                return error.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [pool.submit(join, name) for name in ('citizen', 'citizen2')]
        assert sorted(f.result(timeout=30) for f in results) == [200, 409]
    with pg.sessions() as db:
        assert service.shift_payload(db, db.get(service.VolunteerShift, shift['id']))['registered'] == 1


def test_simultaneous_overlapping_signups_for_same_volunteer(pg_ops):
    pg = pg_ops
    first = setup(pg)
    with pg.sessions() as db:
        second = service.create_shift(db, db.get(User, pg.users['admin']), ShiftCreate(
            title='Synthetic overlapping place', kind='RELIEF', place_id='ernakulam', slots=1,
            starts_at=first['starts_at'], ends_at=first['ends_at']))
    barrier = Barrier(2)
    def join(shift_id):
        with pg.sessions() as db:
            barrier.wait(timeout=10)
            try:
                service.join_shift(db, db.get(User, pg.users['citizen']), shift_id, ShiftSignup(expected_version=1))
                return 200
            except HTTPException as error:
                db.rollback()
                return error.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [pool.submit(join, row['id']) for row in (first, second)]
        assert sorted(f.result(timeout=30) for f in results) == [200, 409]
