from datetime import datetime, timedelta, timezone

import pytest
from backend.tests.test_auth import api, synthetic_password_hash
from backend.models import User
from backend.services import volunteer_service as service


def apply(api, **changes):
    payload = dict(expected_version=0, district_id='ernakulam', ward='Synthetic ward', skills=['logistics'],
                   availability='Weekend mornings', consent=True)
    return api.client.put('/api/volunteers/me', headers=api.headers('citizen'), json=payload | changes)


def approve(api):
    application = apply(api).json()['application']
    return api.client.post(f'/api/volunteers/admin/applications/{application["id"]}/review', headers=api.headers('admin'),
                           json=dict(expected_version=1, decision='APPROVED', note='Reviewed synthetic application')).json()


def shift(api, **changes):
    start = datetime.now(timezone.utc) + timedelta(days=2)
    return api.client.post('/api/volunteers/shifts', headers=api.headers('admin'), json=dict(
        title='Synthetic support duty', kind='FIELD_SUPPORT', place_id='ernakulam', slots=1,
        starts_at=start.isoformat(), ends_at=(start+timedelta(hours=2)).isoformat(), required_skills=['logistics']) | changes)


@pytest.mark.parametrize('role', ['citizen', 'response_team'])
def test_applications_and_rosters_are_admin_only(api, role):
    assert api.client.get('/api/volunteers/admin/applications', headers=api.headers(role)).status_code == 403
    assert api.client.get('/api/volunteers/admin/shifts/1/roster', headers=api.headers(role)).status_code == 403


def test_review_versions_consent_and_no_role_promotion(api):
    assert apply(api, consent=False).status_code == 422
    assert apply(api, district_id='not-in-catalog').status_code == 422
    reviewed = approve(api)
    assert reviewed['status'] == 'APPROVED'
    assert api.client.get('/api/users/me', headers=api.headers('citizen')).json()['role'] == 'citizen'
    assert apply(api).status_code == 409
    assert apply(api, expected_version=reviewed['version']).json()['application']['status'] == 'PENDING'


def test_join_requires_review_skills_versions_and_no_overlap(api):
    row = shift(api).json()
    join = lambda key, version=1: api.client.post(f'/api/volunteers/shifts/{key}/signup', headers=api.headers('citizen'), json={'expected_version': version})
    assert join(row['id']).status_code == 409
    approve(api)
    assert join(row['id'], 99).status_code == 409
    first = join(row['id']).json()
    assert join(row['id']).json()['id'] == first['id']
    other = shift(api, starts_at=row['starts_at'], ends_at=row['ends_at']).json()
    assert join(other['id']).status_code == 409
    cancelled = api.client.post(f'/api/volunteers/signups/{first["id"]}/cancel', headers=api.headers('citizen'),
                               json={'expected_version': first['version'], 'note': 'Synthetic cancellation'})
    assert cancelled.status_code == 200
    assert join(other['id']).status_code == 200


def test_revision_releases_future_signups_and_preserves_history(api):
    application = approve(api)
    row = shift(api).json()
    api.client.post(f'/api/volunteers/shifts/{row["id"]}/signup', headers=api.headers('citizen'), json={'expected_version': 1})
    assert apply(api, expected_version=application['version']).status_code == 200
    data = api.client.get('/api/volunteers/shifts', headers=api.headers('citizen')).json()
    assert data['shifts'][0]['available_slots'] == 1
    assert data['my_signups'][0]['status'] == 'CANCELLED'
    assert len(data['my_signups'][0]['events']) == 2


def test_attendance_clock_transitions_and_inactive_participant(api, monkeypatch):
    approve(api)
    row = shift(api).json()
    signup = api.client.post(f'/api/volunteers/shifts/{row["id"]}/signup', headers=api.headers('citizen'), json={'expected_version': 1}).json()
    endpoint = f'/api/volunteers/admin/signups/{signup["id"]}/attendance'
    mark = lambda status, version: api.client.post(endpoint, headers=api.headers('admin'), json={'status': status, 'expected_version': version, 'note': 'Synthetic attendance'})
    assert mark('CHECKED_IN', 1).status_code == 409
    monkeypatch.setattr(service, 'now', lambda: datetime.fromisoformat(row['starts_at']) + timedelta(minutes=1))
    with api.sessions() as db:
        db.get(User, api.users['citizen']).active = False
        db.commit()
    assert mark('CHECKED_IN', 1).status_code == 409
    with api.sessions() as db:
        db.get(User, api.users['citizen']).active = True
        db.commit()
    assert mark('CHECKED_IN', 1).status_code == 200
    assert mark('COMPLETED', 2).status_code == 409
    monkeypatch.setattr(service, 'now', lambda: datetime.fromisoformat(row['ends_at']) + timedelta(minutes=1))
    assert mark('COMPLETED', 2).status_code == 200
    assert mark('NO_SHOW', 3).status_code == 409


def test_private_fields_never_in_shift_catalog(api):
    approve(api)
    row = shift(api).json()
    api.client.post(f'/api/volunteers/shifts/{row["id"]}/signup', headers=api.headers('citizen'), json={'expected_version': 1})
    public = api.client.get('/api/volunteers/shifts', headers=api.headers('admin')).json()
    assert 'my_signups' in public and public['my_signups'] == []
    assert 'citizen@example.com' not in str(public)
    assert 'password' not in str(api.client.get('/api/volunteers/admin/applications', headers=api.headers('admin')).json())
