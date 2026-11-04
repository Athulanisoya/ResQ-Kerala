"""People explicitly confirm uncertain locations and review unsent question drafts."""
import pytest
from tests.test_web import clients, login, post
from backend.routers import location_analysis


@pytest.fixture(autouse=True)
def no_model_status_call(monkeypatch):
    async def unavailable(settings):
        return {"configured": False, "reason": "Unit test", "model": None}
    monkeypatch.setattr(location_analysis, "get_ollama_status", unavailable)


def report(client, *, location="Paravur", help_required=None, people_affected=None):
    response = client.post('/api/incidents/', json={
        'message': 'Flood water is entering the house. Please help us.',
        'location': location, 'people_affected': people_affected, 'help_required': help_required})
    assert response.status_code == 201, response.text
    return response.json()['id']


def test_ambiguous_place_offers_names_and_owner_confirmation_without_rewriting_report(clients):
    citizen, admin, _ = clients
    login(citizen, 'citizen')
    login(admin, 'admin')
    incident_id = report(citizen)
    path = f'/api/incidents/{incident_id}'
    original = citizen.get(path).json()
    follow_up = citizen.get(path + '/location-clarification').json()
    assert follow_up['requires_clarification'] is True
    assert 'district' in follow_up['question']
    assert len({p['district_id'] for p in follow_up['candidates']}) > 1
    candidate = next(p for p in follow_up['candidates'] if p['kind'] == 'locality')
    confirmed = citizen.post(path + '/location-confirmations', json={
        'place_id': candidate['id'], 'input_hash': follow_up['input_hash'], 'note': 'Confirmed by reporting household'})
    assert confirmed.status_code == 201, confirmed.text
    assert confirmed.json()['requires_clarification'] is False
    assert confirmed.json()['confirmation']['confirmed_by'] == original['user_id']
    after = citizen.get(path).json()
    assert {k: after[k] for k in ('message','location','status')} == {k: original[k] for k in ('message','location','status')}
    analysis = admin.get(path + '/location-analysis').json()
    assert analysis['extraction']['place']['id'] == candidate['id']
    assert 'human confirmation' in analysis['extraction']['reason']
    rerun = admin.post(path + '/location-analysis', json={'use_agent': False})
    assert rerun.status_code == 200
    assert rerun.json()['extraction']['place']['id'] == candidate['id']


def test_unknown_location_accepts_district_only_and_keeps_uncertain_locality_explicit(clients):
    citizen, _, _ = clients
    login(citizen, 'citizen')
    incident_id = report(citizen, location='Unlisted Riverside Junction')
    path = f'/api/incidents/{incident_id}'
    follow_up = citizen.get(path + '/location-clarification').json()
    assert follow_up['candidates'] == []
    assert follow_up['question'] == 'Which district is this locality in?'
    district = follow_up['districts'][0]
    result = citizen.post(path + '/location-confirmations', json={'place_id': district['id'],
        'input_hash': follow_up['input_hash'], 'locality': '<script>unsafe()</script> Junction'})
    assert result.status_code == 201
    assert result.json()['confirmation']['precision'] == 'district'
    assert 'not independently verified' in result.json()['extraction']['reason']
    page = citizen.get(f'/reports/{incident_id}', headers={'HX-Request':'true'})
    assert '&lt;script&gt;unsafe()&lt;/script&gt;' in page.text
    assert '<script>unsafe()</script>' not in page.text


def test_location_confirmation_rejects_unknown_place_stale_input_and_team_write(clients):
    citizen, admin, team = clients
    for client, role in ((citizen,'citizen'),(admin,'admin'),(team,'response_team')):
        login(client, role)
    incident_id = report(citizen)
    path = f'/api/incidents/{incident_id}/location-confirmations'
    follow_up = citizen.get(f'/api/incidents/{incident_id}/location-clarification').json()
    valid = {'place_id': follow_up['candidates'][0]['id'], 'input_hash': follow_up['input_hash']}
    assert citizen.post(path,json={**valid,'input_hash':'0'*64}).status_code == 409
    assert citizen.post(path,json={**valid,'place_id':'invented-place'}).status_code == 422
    assert team.post(path,json=valid).status_code == 403
    assert citizen.get(f'/api/incidents/{incident_id}/location-clarification').json()['confirmation'] is None
    assert admin.post(path,json=valid).status_code == 201


def test_confirmation_ui_requires_csrf_and_is_visible_to_reporter(clients):
    citizen, _, _ = clients
    login(citizen,'citizen')
    incident_id = report(citizen)
    page = citizen.get(f'/reports/{incident_id}',headers={'HX-Request':'true'})
    assert 'Confirm the incident location' in page.text and 'Matched place or district' in page.text
    assert citizen.post(f'/ui/reports/{incident_id}/location-confirmations',data={'_csrf':'wrong'}).status_code == 403


def test_missing_fact_drafts_are_admin_only_reviewable_and_never_send_on_load(clients):
    citizen, admin, _ = clients
    login(citizen,'citizen')
    login(admin,'admin')
    incident_id = report(citizen,location='Unknown Junction')
    path = f'/api/communication/incidents/{incident_id}'
    assert citizen.get(path+'/clarification-suggestions').status_code == 403
    before = admin.get(path+'/clarifications').json()
    suggestions = admin.get(path+'/clarification-suggestions').json()
    assert suggestions['requires_review'] is True
    assert {s['field'] for s in suggestions['suggestions']} == {'location','people','help'}
    draft = admin.get(f'/ui/reports/{incident_id}/clarification-draft?field=people',headers={'HX-Request':'true'})
    assert draft.status_code == 200
    assert 'How many people need help' in draft.text and 'nothing has been sent' in draft.text
    assert admin.get(path+'/clarifications').json() == before
    sent = post(admin,f'/ui/reports/{incident_id}/clarifications',question='How many people need help? Please confirm.',required='yes')
    assert sent.status_code == 200
    assert admin.get(path+'/clarifications').json() != before


def test_complete_facts_and_closed_reports_do_not_draft_irrelevant_questions(clients):
    citizen, admin, _ = clients
    login(citizen,'citizen')
    login(admin,'admin')
    incident_id = report(citizen,location='Kochi',people_affected=3,help_required='Evacuation')
    path = f'/api/communication/incidents/{incident_id}/clarification-suggestions'
    assert admin.get(path).json()['suggestions'] == []
    assert admin.get(f'/ui/reports/{incident_id}/clarification-draft?field=people').status_code == 409


def test_district_only_match_still_asks_for_a_locality_or_landmark(clients):
    citizen, _, _ = clients
    login(citizen, 'citizen')
    incident_id = report(citizen, location='Unlisted Junction, Ernakulam')
    follow_up = citizen.get(f'/api/incidents/{incident_id}/location-clarification').json()
    assert follow_up['extraction']['place']['kind'] == 'district'
    assert follow_up['requires_clarification'] is True
    assert follow_up['question'] == 'Which locality or nearby landmark in Ernakulam is affected?'
