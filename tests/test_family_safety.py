from datetime import datetime, timedelta, timezone
import pytest
from backend.tests.test_auth import api, synthetic_password_hash
from backend.routers import family_safety as service
from backend.models.family_safety import FamilyMember
from sqlalchemy import select

def call(api, role, method, path, body=None):
    return api.client.request(method, '/api/family-safety'+path, headers=api.headers(role), json=body)

def create(api): return call(api, 'citizen', 'POST', '/circles', {'name': 'Synthetic household'}).json()['id']

def invite(api, circle, email='admin@example.com'):
    return call(api, 'citizen', 'POST', f'/circles/{circle}/invitations', {'email': email})

def join(api, circle):
    invite(api, circle)
    record = call(api, 'admin', 'GET', '/circles').json()['invitations'][0]
    return call(api, 'admin', 'POST', f'/invitations/{record["id"]}/accept')

def own(api, role, circle): return next(row for row in call(api, role, 'GET', f'/circles/{circle}').json()['members'] if row['self'])

def checkin(api, role, circle, **changes):
    row = own(api, role, circle)
    return call(api, role, 'PUT', f'/circles/{circle}/checkin', dict(expected_version=row['version'], status='SAFE', location='Private synthetic meeting point', consent=True) | changes)

@pytest.mark.parametrize('role', ['admin', 'response_team'])
def test_no_privileged_bypass_and_no_directory(api, role):
    circle = create(api)
    assert call(api, role, 'GET', '/circles').json()['circles'] == []
    assert call(api, role, 'GET', f'/circles/{circle}').status_code == 404
    assert call(api, role, 'POST', f'/circles/{circle}/invitations', {'email': 'someone@example.com'}).status_code == 404
    assert call(api, role, 'POST', f'/circles/{circle}/close', {'expected_version': 1}).status_code == 404

def test_invitation_consent_new_member_no_old_location_and_withdraw(api):
    circle = create(api)
    assert checkin(api, 'citizen', circle).status_code == 200
    assert invite(api, circle).status_code == 202
    assert call(api, 'admin', 'GET', f'/circles/{circle}').status_code == 404
    # Accept an existing invitation without creating another one.
    record = call(api, 'admin', 'GET', '/circles').json()['invitations'][0]
    assert call(api, 'admin', 'POST', f'/invitations/{record["id"]}/accept').status_code == 200
    viewer = call(api, 'admin', 'GET', f'/circles/{circle}').json()
    assert all(row['location'] is None and row['status'] == 'UNKNOWN' for row in viewer['members'])
    assert checkin(api, 'citizen', circle).status_code == 200
    assert 'Private synthetic meeting point' in call(api, 'admin', 'GET', f'/circles/{circle}').text
    row = own(api, 'citizen', circle)
    assert call(api, 'citizen', 'POST', f'/circles/{circle}/withdraw', {'expected_version': row['version']}).status_code == 200
    assert 'Private synthetic meeting point' not in call(api, 'admin', 'GET', f'/circles/{circle}').text
    notifications = api.client.get('/api/communication/notifications', headers=api.headers('admin'))
    assert 'Private synthetic meeting point' not in notifications.text

def test_generic_invitation_and_revoke_decline_expiry(api, monkeypatch):
    circle = create(api)
    assert invite(api, circle).json() == invite(api, circle, 'missing-account@example.com').json()
    record = call(api, 'admin', 'GET', '/circles').json()['invitations'][0]
    assert call(api, 'response_team', 'POST', f'/invitations/{record["id"]}/accept').status_code == 404
    assert call(api, 'citizen', 'POST', f'/circles/{circle}/invitations/{record["id"]}/revoke').status_code == 200
    assert call(api, 'admin', 'POST', f'/invitations/{record["id"]}/accept').status_code == 404
    invite(api, circle)
    record = call(api, 'admin', 'GET', '/circles').json()['invitations'][0]
    assert call(api, 'admin', 'POST', f'/invitations/{record["id"]}/decline').status_code == 200
    invite(api, circle)
    record = call(api, 'admin', 'GET', '/circles').json()['invitations'][0]
    checked = datetime.now(timezone.utc)+timedelta(days=8)
    monkeypatch.setattr(service, 'now', lambda: checked)
    assert call(api, 'admin', 'GET', '/circles').json()['invitations'] == []
    assert call(api, 'admin', 'POST', f'/invitations/{record["id"]}/accept').status_code == 404

def test_checkin_consent_self_only_and_stale_versions(api, monkeypatch):
    circle = create(api); join(api, circle)
    assert checkin(api, 'citizen', circle, consent=False).status_code == 422
    assert checkin(api, 'citizen', circle, user_id=api.users['admin']).status_code == 422
    assert checkin(api, 'citizen', circle, expected_version=99).status_code == 409
    assert checkin(api, 'citizen', circle).status_code == 200
    checked = datetime.now(timezone.utc)+timedelta(hours=25)
    monkeypatch.setattr(service, 'now', lambda: checked)
    data = call(api, 'admin', 'GET', f'/circles/{circle}').json()
    person = next(row for row in data['members'] if not row['self'])
    assert person['stale'] and person['status'] == 'UNKNOWN' and person['location'] is None

@pytest.mark.parametrize('operation', ['leave', 'remove', 'close'])
def test_ending_membership_immediately_revokes_visibility(api, operation):
    circle = create(api); join(api, circle); checkin(api, 'admin', circle)
    row = own(api, 'admin', circle)
    if operation == 'close':
        result = call(api, 'citizen', 'POST', f'/circles/{circle}/close', {'expected_version': 1})
    elif operation == 'remove':
        result = call(api, 'citizen', 'POST', f'/circles/{circle}/members/{row["id"]}/remove', {'expected_version': row['version']})
    else: result = call(api, 'admin', 'POST', f'/circles/{circle}/leave', {'expected_version': row['version']})
    assert result.status_code == 200
    assert call(api, 'admin', 'GET', f'/circles/{circle}').status_code == 404
    with api.sessions() as db:
        removed = db.scalar(select(FamilyMember).where(FamilyMember.id == row['id']))
        assert removed.location is None and removed.shelter_id is None and removed.status == 'UNKNOWN'

def test_owner_close_required_and_member_cannot_manage(api):
    circle = create(api); join(api, circle)
    assert call(api, 'citizen', 'POST', f'/circles/{circle}/leave', {'expected_version': 1}).status_code == 409
    assert call(api, 'admin', 'POST', f'/circles/{circle}/close', {'expected_version': 1}).status_code == 404
    assert call(api, 'admin', 'POST', f'/circles/{circle}/invitations', {'email': 'someone@example.com'}).status_code == 404
