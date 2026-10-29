"""Admin shelter creation is usable with or without a designated team."""
import pytest

from backend.tests.test_auth import api, synthetic_password_hash
from backend.models import Team
from tests.test_web import clients, login, post


def payload(**changes):
    return {"name": "Community Hall", "location": "School Road, Kochi", "capacity": 30,
            "occupied": 4, "district": "Ernakulam", "locality": "Kochi",
            "address": "Community Hall, School Road", "facilities": "Water and toilets", **changes}


def test_admin_can_add_unassigned_shelter_with_initial_history_and_location_fields(api):
    response = api.client.post('/api/shelters', headers=api.headers('admin'), json=payload())
    assert response.status_code == 201, response.text
    shelter = response.json()
    assert shelter['team_id'] is None
    assert shelter['district'] == 'Ernakulam'
    assert shelter['locality'] == 'Kochi'
    assert shelter['address'] == 'Community Hall, School Road'
    assert shelter['available_capacity'] == 26
    assert shelter['version'] == 1
    history = api.client.get(f"/api/shelters/{shelter['id']}/history", headers=api.headers('admin'))
    assert history.status_code == 200
    assert len(history.json()) == 1
    assert history.json()[0]['changed_by'] == api.users['admin']
    assert history.json()[0]['note'] == 'Shelter created'


@pytest.mark.parametrize('role, code', [(None, 401), ('citizen', 403), ('response_team', 403)])
def test_shelter_creation_requires_an_administrator(api, role, code):
    response = api.client.post('/api/shelters', headers=api.headers(role) if role else {}, json=payload())
    assert response.status_code == code


def test_optional_designation_rejects_offline_or_wrong_team(api):
    with api.sessions() as db:
        offline = Team(name='Offline shelter team', team_type='Shelter', status='OFFLINE')
        active = Team(name='Active shelter team', team_type='Shelter', status='AVAILABLE')
        wrong = Team(name='Rescue team', team_type='Rescue', status='AVAILABLE')
        db.add_all([offline, active, wrong]); db.commit()
        offline_id, active_id, wrong_id = offline.id, active.id, wrong.id
    for team_id in (offline_id, wrong_id, 999999):
        result = api.client.post('/api/shelters', headers=api.headers('admin'), json=payload(team_id=team_id))
        assert result.status_code == 409
    created = api.client.post('/api/shelters', headers=api.headers('admin'), json=payload(team_id=active_id))
    assert created.status_code == 201
    assert created.json()['team_id'] == active_id


def test_expanded_admin_creation_form_works_without_a_shelter_team(clients):
    citizen, admin, _team = clients
    login(admin, 'admin')
    page = admin.get('/shelters', headers={'HX-Request': 'true'})
    assert 'id="add-shelter"' in page.text
    assert 'aria-labelledby="add-shelter-heading"' in page.text
    assert '<summary>Add a shelter</summary>' not in page.text
    assert 'Unassigned' in page.text
    assert 'name="team_id" required' not in page.text
    result = post(admin, '/ui/shelters', name='New community shelter', location='Kochi School Road',
                  capacity='20', occupied='3', district='Ernakulam', locality='Kochi',
                  address='Kochi School Road', facilities='Toilets', team_id='')
    assert result.status_code == 200, result.text
    assert 'Shelter created.' in result.text
    assert 'New community shelter' in result.text
    login(citizen, 'citizen')
    page = citizen.get('/shelters', headers={'HX-Request': 'true'})
    assert 'id="add-shelter"' not in page.text
    assert 'New community shelter' in page.text
    assert post(citizen, '/ui/shelters', name='Denied', location='Kochi', capacity='2', occupied='0').status_code == 403


def test_creation_error_preserves_form_values(clients):
    _citizen, admin, _team = clients
    login(admin, 'admin')
    result = post(admin, '/ui/shelters', name='Keep this shelter', location='Kochi School Road',
                  capacity='2', occupied='3', district='Ernakulam', team_id='')
    assert result.status_code == 422
    assert 'value="Keep this shelter"' in result.text
    assert 'value="Kochi School Road"' in result.text
    assert 'value="Ernakulam"' in result.text
