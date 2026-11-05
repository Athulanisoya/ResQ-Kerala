"""Independent PostgreSQL sessions prove the shelter lock prevents overbooking."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, select

from test_operations_postgres import pg_ops

from backend.models import User
from backend.models.shelter import Shelter
from backend.models.shelter_registration import ShelterRegistration
from backend.schemas.shelter_registration_schema import ShelterRegistrationCreate
from backend.services.shelter_registration_service import reserve
from backend.services.shelter_service import create_shelter


def test_concurrent_citizens_cannot_overbook_last_spaces(pg_ops):
    with pg_ops.sessions() as db:
        shelter = create_shelter(db, {"name": "Synthetic concurrent reservation shelter", "location": "Aluva",
            "capacity": 3, "occupied": 0}, db.get(User, pg_ops.users["admin"]))
        shelter_id = shelter.id
    barrier = Barrier(2)

    def attempt(citizen):
        with pg_ops.sessions() as db:
            user = db.get(User, pg_ops.users[citizen])
            data = ShelterRegistrationCreate(party_size=2, origin_district="ernakulam", origin_locality="Aluva",
                                             request_key=uuid4())
            barrier.wait(timeout=10)
            try:
                reserve(db, user, shelter_id, data)
                return 201
            except HTTPException as error:
                db.rollback()
                return error.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [pool.submit(attempt, citizen) for citizen in ("citizen", "citizen2")]
        assert sorted(result.result(timeout=30) for result in results) == [201, 409]
    with pg_ops.sessions() as db:
        assert db.get(Shelter, shelter_id).occupied == 2
        assert db.scalar(select(func.count()).select_from(ShelterRegistration)) == 1
