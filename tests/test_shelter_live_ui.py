"""Availability refreshes independently of administrator editing forms."""
import json
from tests.test_web import clients, login, post


def create_shelter(admin):
    response = admin.post('/api/shelters', json={
        'name': 'Live community shelter', 'location': 'Kochi school', 'capacity': 20, 'occupied': 3})
    assert response.status_code == 201, response.text
    return response.json()


def test_live_fragment_shows_latest_values_without_replacing_editors(clients):
    citizen, admin, _team = clients
    login(admin, 'admin'); login(citizen, 'citizen')
    shelter = create_shelter(admin)
    page = citizen.get('/shelters?q=Live', headers={'HX-Request': 'true'})
    assert 'every 3s' in page.text
    assert 'document.visibilityState' in page.text
    assert 'id="shelter-editor"' in page.text
    assert '/ui/shelters/live?' in page.text
    assert 'q=Live' in page.text
    update = admin.patch(f"/api/shelters/{shelter['id']}", json={
        'capacity': 25, 'occupied': 10, 'expected_version': 1, 'note': 'Reception count updated'})
    assert update.status_code == 200
    live = citizen.get('/ui/shelters/live?q=Live', headers={'HX-Request': 'true'})
    assert live.status_code == 200
    assert 'data-capacity>25<' in live.text
    assert 'data-occupied>10<' in live.text
    assert 'data-available>15<' in live.text
    assert '<form' not in live.text
    assert 'Update capacity' not in live.text
    assert 'Add a shelter' not in live.text


def test_capacity_editor_checks_auth_preserves_conflicts_and_triggers_refresh(clients):
    citizen, admin, _team = clients
    login(admin, 'admin'); login(citizen, 'citizen')
    shelter = create_shelter(admin)
    editor = f"/ui/shelters/{shelter['id']}/editor"
    path = f"/ui/shelters/{shelter['id']}/capacity"
    assert citizen.get(editor, headers={'HX-Request': 'true'}).status_code == 403
    denied = post(citizen, path, capacity='30', occupied='4', expected_version='1', note='Not permitted')
    assert denied.status_code == 403
    form = admin.get(editor, headers={'HX-Request': 'true'})
    assert form.status_code == 200 and 'name="expected_version" value="1"' in form.text
    saved = post(admin, path, capacity='30', occupied='5', expected_version='1', note='New reception count')
    assert saved.status_code == 200
    assert json.loads(saved.headers['HX-Trigger']) == {'resq:shelters-changed': True}
    assert 'name="expected_version" value="2"' in saved.text
    conflict = post(admin, path, capacity='99', occupied='10', expected_version='1', note='Preserve my draft')
    assert conflict.status_code == 409
    assert 'value="99"' in conflict.text
    assert 'value="Preserve my draft"' in conflict.text
    assert 'Reload latest values' in conflict.text
    invalid = post(admin, path, capacity='3', occupied='4', expected_version='2', note='Invalid occupancy')
    assert invalid.status_code == 422
    assert 'value="3"' in invalid.text
    assert admin.get(f"/api/shelters/{shelter['id']}").json()['capacity'] == 30


def test_availability_filter_removes_full_shelters_on_refresh(clients):
    citizen, admin, _team = clients
    login(admin, 'admin'); login(citizen, 'citizen')
    shelter = create_shelter(admin)
    path = '/ui/shelters/live?available_only=true'
    assert 'Live community shelter' in citizen.get(path, headers={'HX-Request': 'true'}).text
    admin.patch(f"/api/shelters/{shelter['id']}", json={
        'capacity': 20, 'occupied': 20, 'expected_version': 1, 'note': 'All places now occupied'})
    refreshed = citizen.get(path, headers={'HX-Request': 'true'})
    assert 'Live community shelter' not in refreshed.text
    assert 'No matching shelter records' in refreshed.text


def test_invalid_nearby_filter_stays_scoped_during_live_refresh(clients):
    citizen, _admin, _team = clients
    login(citizen, 'citizen')
    page = citizen.get('/shelters?q=Kochi&latitude=10', headers={'HX-Request': 'true'})
    assert page.status_code == 422
    assert 'Provide both latitude and longitude' in page.text
    assert 'q=Kochi' in page.text and 'latitude=10' in page.text
    live = citizen.get('/ui/shelters/live?q=Kochi&latitude=10', headers={'HX-Request': 'true'})
    assert live.status_code == 200
    assert 'retry automatically' in live.text
    assert 'data-shelter-id' not in live.text


def test_nonfinite_coordinates_return_validation_errors_instead_of_500(clients):
    citizen, admin, _team = clients
    login(admin, 'admin')
    shelter = create_shelter(admin)
    for invalid in ('NaN', 'Infinity', '-Infinity'):
        created = post(admin, '/ui/shelters', name='Invalid coordinate', location='Kochi',
                       capacity='5', occupied='0', latitude=invalid, longitude='76')
        assert created.status_code == 422
        updated = post(admin, f"/ui/shelters/{shelter['id']}/capacity", capacity='20', occupied='3',
                       expected_version='1', note='Invalid coordinate', latitude=invalid, longitude='76')
        assert updated.status_code == 422
