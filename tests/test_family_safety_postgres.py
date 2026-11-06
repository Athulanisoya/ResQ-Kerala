from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from fastapi import HTTPException
from sqlalchemy import select
from test_operations_postgres import pg_ops
from backend.models import User
from backend.models.family_safety import FamilyMember, FamilyInvitation
from backend.routers import family_safety as service

def setup(pg):
    with pg.sessions() as db:
        owner = db.get(User, pg.users['citizen'])
        circle = service.create(service.CircleInput(name='Synthetic private circle'), db, owner)['id']
        service.invite(circle, service.InviteInput(email='pg-admin@example.com'), db, owner)
        invitation = db.scalar(select(FamilyInvitation).where(FamilyInvitation.circle_id == circle)).id
    return circle, invitation

def race(functions):
    barrier = Barrier(len(functions))
    def run(fn):
        barrier.wait(timeout=10)
        try: fn(); return 200
        except HTTPException as error: return error.status_code
    with ThreadPoolExecutor(max_workers=len(functions)) as pool:
        futures = [pool.submit(run, fn) for fn in functions]
        return [future.result(timeout=30) for future in futures]

def test_accept_and_revoke_are_serialized(pg_ops):
    pg = pg_ops; circle, invitation = setup(pg)
    def accept():
        with pg.sessions() as db: service.decide(invitation, 'accept', db, db.get(User, pg.users['admin']))
    def revoke():
        with pg.sessions() as db: service.revoke(circle, invitation, db, db.get(User, pg.users['citizen']))
    assert sorted(race([accept, revoke])) == [200, 404]
    with pg.sessions() as db:
        record = db.get(FamilyInvitation, invitation)
        membership = db.scalar(select(FamilyMember).where(FamilyMember.circle_id == circle, FamilyMember.user_id == pg.users['admin']))
        assert (record.status == 'ACCEPTED') == bool(membership and membership.left_at is None)

def test_leave_racing_checkin_cannot_restore_location(pg_ops):
    pg = pg_ops; circle, invitation = setup(pg)
    with pg.sessions() as db: service.decide(invitation, 'accept', db, db.get(User, pg.users['admin']))
    def share():
        with pg.sessions() as db:
            service.checkin(circle, service.CheckinInput(expected_version=1, status='SAFE', location='Private test point', consent=True), db, db.get(User, pg.users['admin']))
    def leave():
        with pg.sessions() as db:
            # Read the latest version under the same circle lock before consent withdrawal.
            _, member = service.member(db, circle, db.get(User, pg.users['admin']), lock=True)
            service.leave(circle, service.VersionInput(expected_version=member.version), db, db.get(User, pg.users['admin']))
    results = race([share, leave])
    assert 200 in results and set(results) <= {200, 404, 409}
    with pg.sessions() as db:
        row = db.scalar(select(FamilyMember).where(FamilyMember.circle_id == circle, FamilyMember.user_id == pg.users['admin']))
        assert row.left_at and row.location is None and row.status == 'UNKNOWN'
