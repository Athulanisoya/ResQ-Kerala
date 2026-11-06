from datetime import date, timedelta
import pytest
from backend.tests.test_auth import api, synthetic_password_hash
from backend.services.preparedness_service import REVISION, ITEMS, SOURCES

def save(api, **changes):
    return api.client.put('/api/preparedness/me', headers=api.headers('citizen'), json=dict(
        expected_version=0, guidance_revision=REVISION, completed=['contacts', 'meeting_points'], language='ml',
        nearby_meeting='Private synthetic meeting point', outside_meeting='Private second point',
        contacts=[{'name': 'Synthetic contact', 'phone': '0000000000', 'relationship': 'Household'}],
        support_plan='Synthetic household support instructions', next_review_on=(date.today()-timedelta(days=2)).isoformat(), reviewed=True) | changes)

def test_saved_plan_progress_review_and_scope(api):
    assert save(api).status_code == 200
    plan = api.client.get('/api/preparedness/me', headers=api.headers('citizen')).json()
    assert plan['version'] == 1 and plan['review_due'] and plan['reviewed_at'] and plan['language'] == 'ml'
    assert set(plan['completed']) == {'contacts', 'meeting_points'}
    assert save(api).status_code == 409
    for role in ('admin', 'response_team'):
        other = api.client.get('/api/preparedness/me', headers=api.headers(role))
        assert other.status_code == 200 and other.json()['version'] == 0
        assert 'Private synthetic' not in other.text and '0000000000' not in other.text
    assert api.client.get('/api/preparedness/1', headers=api.headers('admin')).status_code == 404
    assert save(api, expected_version=1, reviewed=False).json()['reviewed_at'] is None

@pytest.mark.parametrize('changes', [dict(completed=['unknown']), dict(guidance_revision='old'), dict(language='xx'),
    dict(user_id=123), dict(contacts=[{'name':'No number'}]), dict(nearby_meeting='a'*256)])
def test_invalid_plan_does_not_save(api, changes):
    assert save(api, **changes).status_code == 422
    assert api.client.get('/api/preparedness/me', headers=api.headers('citizen')).json()['version'] == 0

def test_guidance_is_source_linked_and_bilingual(api):
    r = api.client.get('/api/preparedness/guidance', headers=api.headers('citizen'))
    assert r.status_code == 200 and r.json()['revision'] == REVISION
    assert len({item['id'] for item in ITEMS}) == len(ITEMS) == 8
    for item in ITEMS:
        assert item['source'] in SOURCES and item['en'] and item['ml']
        assert SOURCES[item['source']]['url'].startswith(('https://sdma.kerala.gov.in/', 'https://ndma.gov.in/'))
    assert 'private synthetic' not in r.text.lower()
