"""Parent-team locks serialize competing first-time operating profiles."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from fastapi import HTTPException

from backend.models import User
from backend.models.team_coverage import TeamOperationalProfile
from backend.schemas.team_coverage_schema import TeamCoverageUpdate
from backend.services.team_recommendation_service import update_coverage
from test_operations_postgres import pg_ops


def test_competing_initial_coverage_edits_require_current_version(pg_ops):
    barrier = Barrier(2)
    target = pg_ops.teams["rescue"]

    def save(area):
        with pg_ops.sessions() as db:
            actor = db.get(User, pg_ops.users["admin"])
            barrier.wait(timeout=10)
            try:
                update_coverage(db, target, actor, TeamCoverageUpdate(expected_version=0, area_ids=[area]))
                return 200
            except HTTPException as error:
                db.rollback(); return error.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [pool.submit(save, area) for area in ("ernakulam", "thrissur")]
        assert sorted(result.result(timeout=30) for result in results) == [200, 409]
    with pg_ops.sessions() as db:
        profile = db.get(TeamOperationalProfile, target)
        assert profile.version == 1 and profile.area_ids in [["ernakulam"], ["thrissur"]]
