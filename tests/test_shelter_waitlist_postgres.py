"""Independent database sessions contend on the same temporary capacity hold."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, select

from test_operations_postgres import pg_ops

from backend.models import User
from backend.models.shelter import Shelter
from backend.models.shelter_registration import ShelterRegistration
from backend.models.shelter_waitlist import ShelterWaitlist
from backend.schemas.shelter_registration_schema import ShelterRegistrationCreate
from backend.schemas.shelter_waitlist_schema import ShelterWaitlistAction, ShelterWaitlistCreate
from backend.services.shelter_registration_service import reserve
from backend.services.shelter_service import create_shelter
from backend.services.shelter_waitlist_service import accept, join, process_waitlists


def setup_offer(pg_ops):
    with pg_ops.sessions() as db:
        shelter = create_shelter(db, {"name": "Synthetic PG waitlist shelter", "location": "Aluva", "capacity": 3, "occupied": 0}, db.get(User, pg_ops.users["admin"]))
        row, _ = join(db, db.get(User, pg_ops.users["citizen"]), shelter.id,
            ShelterWaitlistCreate(party_size=2, origin_district="ernakulam", origin_locality="Aluva", request_key=uuid4()))
        return shelter.id, row["id"], row["version"]


def test_two_simultaneous_accepts_create_one_registration_and_keep_one_hold(pg_ops):
    shelter_id, entry_id, version = setup_offer(pg_ops)
    barrier = Barrier(2)
    def attempt():
        with pg_ops.sessions() as db:
            user = db.get(User, pg_ops.users["citizen"])
            barrier.wait(timeout=10)
            return accept(db, user, entry_id, ShelterWaitlistAction(expected_version=version))["registration_id"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(attempt) for _ in range(2)]
        assert len({future.result(timeout=30) for future in futures}) == 1
    with pg_ops.sessions() as db:
        assert db.get(Shelter, shelter_id).occupied == 2
        assert db.scalar(select(func.count()).select_from(ShelterRegistration)) == 1


def test_accept_and_competing_direct_reservation_cannot_overbook_held_spaces(pg_ops):
    shelter_id, entry_id, version = setup_offer(pg_ops)
    barrier = Barrier(2)
    def accept_offer():
        with pg_ops.sessions() as db:
            user = db.get(User, pg_ops.users["citizen"]); barrier.wait(timeout=10)
            accept(db, user, entry_id, ShelterWaitlistAction(expected_version=version)); return 200
    def direct():
        with pg_ops.sessions() as db:
            user = db.get(User, pg_ops.users["citizen2"]); barrier.wait(timeout=10)
            try:
                reserve(db, user, shelter_id, ShelterRegistrationCreate(party_size=2, origin_district="ernakulam", origin_locality="Aluva", request_key=uuid4()))
                return 201
            except HTTPException as error:
                db.rollback(); return error.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.submit(accept_offer), pool.submit(direct)
        assert first.result(timeout=30) == 200 and second.result(timeout=30) == 409
    with pg_ops.sessions() as db:
        assert db.get(Shelter, shelter_id).occupied == 2
        assert db.scalar(select(func.count()).select_from(ShelterRegistration)) == 1


def test_two_worker_ticks_expire_a_hold_only_once(pg_ops):
    shelter_id, entry_id, _ = setup_offer(pg_ops)
    checked = datetime.now(timezone.utc)
    with pg_ops.sessions() as db:
        db.get(ShelterWaitlist, entry_id).offer_expires_at = checked - timedelta(seconds=1); db.commit()
    barrier = Barrier(2)
    def attempt():
        with pg_ops.sessions() as db:
            barrier.wait(timeout=10)
            result = process_waitlists(db, now=checked); db.commit(); return result["expired"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(attempt) for _ in range(2)]
        assert sorted(future.result(timeout=30) for future in futures) == [0, 1]
    with pg_ops.sessions() as db:
        assert db.get(Shelter, shelter_id).occupied == 0
        assert db.get(ShelterWaitlist, entry_id).status == "EXPIRED"
