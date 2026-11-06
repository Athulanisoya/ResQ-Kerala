from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

from backend.tests.test_auth import api, synthetic_password_hash
from backend.models.communication import Notification
from backend.services.automation_notifications import notify_user
from backend.services.automation_runner import run_cycle


def test_generic_notifications_are_private_readable_and_retry_safe(api):
    with api.sessions() as db:
        assert notify_user(db,api.users['citizen'],'Synthetic area alert','Synthetic active notice','automation:test:1','/alerts')
        assert notify_user(db,api.users['citizen'],'Synthetic area alert','Synthetic active notice','automation:test:1','/alerts') is None
        db.commit()
    path='/api/communication/notifications'
    mine=api.client.get(path,headers=api.headers('citizen')).json()
    assert mine['unread_count']==1 and mine['notifications'][0]['target_url']=='/alerts'
    notification=mine['notifications'][0]
    assert notification['incident_id'] is None
    assert api.client.post(f"{path}/{notification['id']}/read",headers=api.headers('admin')).status_code==404
    assert api.client.post(f"{path}/{notification['id']}/read",headers=api.headers('citizen')).status_code==200
    assert api.client.get(path,headers=api.headers('citizen')).json()['unread_count']==0


@pytest.mark.parametrize('target',['https://example.com','//example.com','javascript:alert(1)','/ui/shelters/1/capacity','/admin','/alerts\n'])
def test_notifications_cannot_link_external_or_mutating_targets(api,target):
    with api.sessions() as db:
        with pytest.raises(ValueError):
            notify_user(db,api.users['citizen'],'Title','Message','bad-target',target)
        assert db.scalar(select(func.count(Notification.id)))==0


def test_policy_admin_scope_versions_and_validation(api):
    path='/api/admin/automations'
    assert api.client.get(path,headers=api.headers('citizen')).status_code==403
    initial=api.client.get(path,headers=api.headers('admin')).json()
    assert initial['policy']['version']==0
    payload={'stale_minutes':30,'reminder_minutes':60,'escalation_minutes':120,'waitlist_offer_minutes':15,'expected_version':0}
    result=api.client.put(path,headers=api.headers('admin'),json=payload)
    assert result.status_code==200 and result.json()['version']==1
    assert api.client.put(path,headers=api.headers('admin'),json=payload).status_code==409
    assert api.client.put(path,headers=api.headers('admin'),json={**payload,'expected_version':1,'escalation_minutes':5}).status_code==422
    assert api.client.post(path+'/run',headers=api.headers('response_team')).status_code==403


def test_worker_cycle_persists_successful_status(api):
    result=run_cycle(api.sessions,now=datetime(2026,11,5,tzinfo=timezone.utc))
    assert not result['has_error'] and set(result['jobs'])=={'area_alerts','shelter_reminders','waitlists'}
    state=api.client.get('/api/admin/automations',headers=api.headers('admin')).json()['runtime']
    assert state and not state['has_error'] and state['last_success_at']


def test_failed_job_is_isolated_and_private_error_text_is_not_retained(api, monkeypatch):
    from backend.services import shelter_reminder_service
    def fail(*args, **kwargs):
        raise RuntimeError('synthetic-private-database-diagnostic')
    monkeypatch.setattr(shelter_reminder_service, 'process_shelter_reminders', fail)
    result=run_cycle(api.sessions,now=datetime(2026,11,5,tzinfo=timezone.utc))
    assert result['has_error']
    assert result['jobs']['shelter_reminders']['status']=='failed'
    assert result['jobs']['area_alerts']['status']=='ok'
    assert result['jobs']['waitlists']['status']=='ok'
    state=api.client.get('/api/admin/automations',headers=api.headers('admin')).json()['runtime']
    assert state['has_error'] and state['last_success_at'] is None
    assert 'synthetic-private' not in str(state)
