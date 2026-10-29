"""Concurrent capacity updates retain optimistic version protection."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest
from fastapi import HTTPException
from sqlalchemy import select, func
from backend.models import User
from backend.models.shelter import Shelter, ShelterUpdate
from backend.schemas.shelter_schema import ShelterPatch
from backend.services.shelter_service import create_shelter, update_shelter
from test_operations_postgres import pg_ops


def test_capacity_writers_cannot_silently_overwrite_each_other(pg_ops):
    with pg_ops.sessions() as db:
        admin = db.get(User, pg_ops.users['admin'])
        shelter = create_shelter(db, {'name': 'Synthetic live shelter', 'location': 'Kochi',
                                     'capacity': 20, 'occupied': 2}, admin)
        shelter_id = shelter.id
    gate = Barrier(2)
    def attempt(occupied):
        with pg_ops.sessions() as db:
            admin = db.get(User, pg_ops.users['admin'])
            data = ShelterPatch(capacity=20, occupied=occupied, expected_version=1, note='Reception count')
            gate.wait(timeout=10)
            try:
                return update_shelter(db, shelter_id, admin, data)['version']
            except HTTPException as error:
                db.rollback()
                return error.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = pool.submit(attempt, 3), pool.submit(attempt, 4)
        assert sorted([a.result(timeout=30), b.result(timeout=30)]) == [2, 409]
    with pg_ops.sessions() as db:
        assert db.get(Shelter, shelter_id).version == 2
        assert db.scalar(select(func.count()).select_from(ShelterUpdate).where(ShelterUpdate.shelter_id == shelter_id)) == 2
