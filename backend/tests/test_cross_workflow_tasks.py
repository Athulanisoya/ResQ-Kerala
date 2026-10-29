"""Exercise both legacy and operations routes in a single response lifecycle."""
from backend.tests.test_auth import api, synthetic_password_hash
from backend.tests.test_workflows import workflow, submit, review, assign
from backend.models import Incident, Team
from backend.models.operations import IncidentTask, IncidentTaskEvent
from backend.models.relief import ReliefRequest
from sqlalchemy import select


def start(api):
    incident_id = submit(api).json()['id']
    assert review(api, incident_id).status_code == 200
    assert assign(api, incident_id).status_code == 200
    return incident_id


def test_legacy_accept_and_progress_can_continue_through_operations(workflow):
    api = workflow
    incident_id = start(api)
    team = api.headers('response_team')
    admin = api.headers('admin')
    assert api.client.post(f'/api/teams/incidents/{incident_id}/accept', headers=team).status_code == 200
    progress = api.client.post(f'/api/operations/incidents/{incident_id}/progress', headers=team, json={'status':'EN_ROUTE'})
    assert progress.status_code == 200, progress.text
    legacy = api.client.patch(f'/api/incidents/{incident_id}/progress', headers=team, json={'status':'IN_PROGRESS','note':'Starting rescue'})
    assert legacy.status_code == 200, legacy.text
    assert api.client.patch(f'/api/incidents/{incident_id}/progress', headers=team, json={'status':'RESCUE_COMPLETED','note':'Rescue complete'}).status_code == 200
    handoff = api.client.post(f'/api/operations/incidents/{incident_id}/handoff', headers=admin,
                              json={'team_id':api.other_team_id, 'note':'Rescue complete; transfer to relief'})
    assert handoff.status_code == 200, handoff.text
    with api.sessions() as db:
        tasks = list(db.scalars(select(IncidentTask).where(IncidentTask.incident_id == incident_id).order_by(IncidentTask.id)))
        assert [row.status for row in tasks] == ['HANDED_OFF', 'ASSIGNED']
        assert tasks[0].accepted_at is not None and not tasks[0].active and tasks[1].active
        statuses = list(db.scalars(select(IncidentTaskEvent.status).where(IncidentTaskEvent.task_id == tasks[0].id).order_by(IncidentTaskEvent.id)))
        assert statuses == ['ASSIGNED', 'ACCEPTED', 'EN_ROUTE', 'IN_PROGRESS', 'RESCUE_COMPLETED', 'HANDED_OFF']
        assert db.get(Team, api.team_id).status == 'AVAILABLE'


def test_operations_accept_and_legacy_handoff_preserve_task_history(workflow):
    api = workflow
    incident_id = start(api)
    team = api.headers('response_team')
    admin = api.headers('admin')
    assert api.client.post(f'/api/operations/incidents/{incident_id}/accept', headers=team, json={}).status_code == 200
    assert api.client.patch(f'/api/incidents/{incident_id}/progress', headers=team, json={'status':'EN_ROUTE','note':'Travelling'}).status_code == 200
    assert api.client.post(f'/api/operations/incidents/{incident_id}/progress', headers=team, json={'status':'IN_PROGRESS'}).status_code == 200
    assert api.client.patch(f'/api/incidents/{incident_id}/progress', headers=team, json={'status':'RESCUE_COMPLETED','note':'Rescue complete'}).status_code == 200
    with api.sessions() as db:
        db.add(ReliefRequest(incident_id=incident_id, item='WATER', quantity=5, fulfilled=0, created_by=api.users['citizen']))
        db.commit()
    handoff = api.client.post(f'/api/incidents/{incident_id}/relief-handoff', headers=admin,
                              json={'team_id':api.other_team_id, 'note':'Rescue complete; transfer to relief'})
    assert handoff.status_code == 200, handoff.text
    with api.sessions() as db:
        tasks = list(db.scalars(select(IncidentTask).where(IncidentTask.incident_id == incident_id).order_by(IncidentTask.id)))
        assert [row.status for row in tasks] == ['HANDED_OFF', 'ASSIGNED']
        assert not tasks[0].active and tasks[1].active and tasks[0].ended_at is not None
        assert db.get(Team, api.team_id).status == 'AVAILABLE'
        assert db.get(Team, api.other_team_id).status == 'BUSY'
    assert api.client.post(f'/api/operations/incidents/{incident_id}/accept', headers=api.headers('other_team'), json={}).status_code == 200
