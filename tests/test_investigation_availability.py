"""Investigation assignment availability and concurrent offline protection."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from test_operations_postgres import pg_ops
from backend.models import Team, User
from backend.models.investigation import InvestigationTeamAssignment
from backend.routers.management import TeamChange, change_team
from backend.services.investigation_service import assign_investigation_team
from tests.test_investigations import api, investigation_password_hash


def test_assignment_rejects_offline_investigation_team(api):
    with api.sessions() as db:
        team = Team(name='Offline investigators', team_type='Investigation', status='OFFLINE')
        db.add(team); db.commit(); team_id = team.id
    response = api.client.post(f'{api.path}/investigation/team', headers=api.headers(), json={'team_id':team_id})
    assert response.status_code == 409
    assert 'offline' in response.text.lower()


def test_assignment_and_offline_change_cannot_both_win(pg_ops):
    with pg_ops.sessions() as db:
        team = Team(name='Synthetic investigation race', team_type='Investigation', status='AVAILABLE')
        db.add(team); db.commit(); team_id = team.id
    barrier = Barrier(2)
    def assign():
        with pg_ops.sessions() as db:
            actor = db.get(User, pg_ops.users['admin'])
            barrier.wait(timeout=10)
            try:
                assign_investigation_team(db, pg_ops.incidents[0], actor, team_id)
                return 200
            except HTTPException as exc:
                db.rollback(); return exc.status_code
    def take_offline():
        with pg_ops.sessions() as db:
            actor = db.get(User, pg_ops.users['admin'])
            barrier.wait(timeout=10)
            try:
                change_team(team_id, TeamChange(name='Synthetic investigation race', status='OFFLINE'), db, actor)
                return 200
            except HTTPException as exc:
                db.rollback(); return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(assign); b = pool.submit(take_offline)
        assert sorted([a.result(timeout=30), b.result(timeout=30)]) == [200, 409]
    with pg_ops.sessions() as db:
        team = db.get(Team, team_id)
        assignment = db.scalar(select(InvestigationTeamAssignment).where(InvestigationTeamAssignment.team_id == team_id))
        assert not (team.status == 'OFFLINE' and assignment is not None)
