from datetime import datetime, timedelta, timezone
from backend.tests.test_auth import api, synthetic_password_hash
from backend.models import Shelter, Team, User
from backend.models.shelter_facilities import ShelterFacilities, ShelterFacilitiesEvent
from backend.services.shelter_facilities_service import LABELS
from sqlalchemy import select, func

def create(api):
    return api.client.post('/api/shelters', headers=api.headers('admin'), json={
        'name': 'Synthetic accessible shelter', 'location': 'Aluva', 'capacity': 10, 'occupied': 0}).json()

def update(api, id, role='admin', **changes):
    return api.client.patch(f'/api/shelters/{id}/facilities', headers=api.headers(role), json={
        'expected_version': 0, **{key: 'UNKNOWN' for key in LABELS}, 'confirmed': True,
        'note': 'Synthetic staff facility inspection', 'wheelchair_access': 'YES', 'charging': 'YES', **changes})

def test_unknown_does_not_match_and_filters_use_all_requirements(api):
    shelter = create(api)
    assert all(v == 'UNKNOWN' for v in shelter['facility_details'].values())
    search = lambda query: api.client.get('/api/shelters?'+query, headers=api.headers('citizen'))
    assert search('facility=wheelchair_access').json() == []
    assert update(api, shelter['id']).status_code == 200
    assert len(search('facility=wheelchair_access&facility=charging').json()) == 1
    assert search('facility=wheelchair_access&facility=accessible_toilets').json() == []
    assert search('facility=not-a-facility').status_code == 422

def test_permissions_confirmation_versions_and_capacity_clock(api):
    shelter = create(api)
    assert update(api, shelter['id'], 'citizen').status_code == 403
    assert update(api, shelter['id'], 'response_team').status_code == 403
    assert update(api, shelter['id'], confirmed=False).status_code == 422
    assert update(api, shelter['id'], wheelchair_access='maybe').status_code == 422
    with api.sessions() as db:
        team = Team(name='Synthetic facility team', team_type='Shelter'); db.add(team); db.flush()
        db.get(User, api.users['response_team']).team_id = team.id
        db.get(Shelter, shelter['id']).team_id = team.id; db.commit()
    assert update(api, shelter['id'], 'response_team').status_code == 200
    assert update(api, shelter['id']).status_code == 409
    data = api.client.get(f'/api/shelters/{shelter["id"]}', headers=api.headers('citizen')).json()
    assert data['facility_freshness'] == 'current'
    assert datetime.fromisoformat(data['capacity_confirmed_at']).replace(tzinfo=timezone.utc) == datetime.fromisoformat(shelter['capacity_confirmed_at']).replace(tzinfo=timezone.utc)
    assert data['occupied'] == shelter['occupied'] and data['version'] == shelter['version']
    with api.sessions() as db:
        assert db.scalar(select(func.count()).select_from(ShelterFacilitiesEvent)) == 1

def test_stale_facilities_remain_visible_but_cannot_match(api):
    shelter = create(api); update(api, shelter['id'])
    with api.sessions() as db:
        db.get(ShelterFacilities, shelter['id']).confirmed_at = datetime.now(timezone.utc)-timedelta(days=31); db.commit()
    details = api.client.get(f'/api/shelters/{shelter["id"]}', headers=api.headers('citizen')).json()
    assert details['facility_freshness'] == 'stale' and details['facility_details']['wheelchair_access'] == 'YES'
    assert api.client.get('/api/shelters?facility=wheelchair_access', headers=api.headers('citizen')).json() == []
