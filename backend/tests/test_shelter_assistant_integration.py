"""Cross-workflow shelter and assistant checks using synthetic data."""
import asyncio

from backend.tests.test_relief_shelters import services, shelter_payload, api, synthetic_password_hash
from backend.ai.shelter_agent import AryaAgentContext, _local_fallback, answer_question, _shelter_payload, _extract_sources
from backend.models import Incident, User
from backend.models.shelter import Shelter


def test_nearby_search_and_facility_updates(services):
    api = services
    first = api.client.post('/api/shelters', headers=api.headers('admin'), json=shelter_payload(api,
        name='Far Shelter', latitude=10.1, longitude=76.3, facilities='Water, toilets'))
    second = api.client.post('/api/shelters', headers=api.headers('admin'), json=shelter_payload(api,
        name='Near Shelter', latitude=10.0, longitude=76.3))
    assert first.status_code == second.status_code == 201
    assert first.json()['facilities'] == 'Water, toilets'
    nearest = api.client.get('/api/shelters?latitude=10&longitude=76.3', headers=api.headers('citizen'))
    assert [row['name'] for row in nearest.json()] == ['Near Shelter', 'Far Shelter']
    assert nearest.json()[0]['distance_km'] == 0
    assert api.client.get('/api/shelters?latitude=10', headers=api.headers('citizen')).status_code == 422
    updated = api.client.patch(f"/api/shelters/{first.json()['id']}", headers=api.headers('shelter'), json={
        'capacity':30,'occupied':10,'expected_version':1,'note':'Temporarily closed','status':'CLOSED','facilities':'Water'})
    assert updated.status_code == 200 and updated.json()['status'] == 'CLOSED'
    assert updated.json()['facilities'] == 'Water'
    assert api.client.patch(f"/api/shelters/{first.json()['id']}", headers=api.headers('other_shelter'), json={
        'capacity':30,'occupied':10,'expected_version':2,'note':'Not authorized'}).status_code == 403


def test_local_assistant_never_substitutes_unrelated_shelters(services):
    api = services
    with api.sessions() as db:
        db.add(Shelter(name='Harbour Hall', location='Kochi School', capacity=10, occupied=0))
        db.commit()
        no_match = _local_fallback(AryaAgentContext(db=db, question='Find shelters in Kannur'))
        assert 'Harbour Hall' not in no_match['answer']
        generic = _local_fallback(AryaAgentContext(db=db, question='Show available shelters'))
        assert 'provide a district' in generic['answer'].lower()
        assert 'Harbour Hall' not in generic['answer']
        match = _local_fallback(AryaAgentContext(db=db, question='Find shelter at Kochi School'))
        assert 'Harbour Hall' in match['answer']
        assert _shelter_payload(db.query(Shelter).first())['location'] == 'Kochi School'
        contacts = _local_fallback(AryaAgentContext(db=db, question='Emergency contact number'))
        assert '112' in contacts['answer'] and 'https://112.gov.in/' in contacts['answer']
        guidance = _local_fallback(AryaAgentContext(db=db, question='Flood preparedness guidance'))
        assert guidance['sources'] and guidance['sources'][0]['review_required'] is True
        assert 'owner verification' in guidance['answer'].lower()
        assert 'approval_status' in guidance['sources'][0]



def test_assistant_status_respects_owner_and_team(services):
    api = services
    with api.sessions() as db:
        own = db.get(Incident, api.incident_id)
        citizen = db.get(User, api.users['citizen'])
        other = db.get(User, api.users['other_shelter'])
        visible = asyncio.run(answer_question(db, f'Status of report #{own.id}', user=citizen))
        hidden = asyncio.run(answer_question(db, f'Status of report #{own.id}', user=other))
        assert 'In Progress' in visible['answer']
        assert 'No accessible report matched' in hidden['answer']
        assert 'In Progress' not in hidden['answer']
        summary = asyncio.run(answer_question(db, f'Summarize my report #{own.id}', user=citizen))
        denied = asyncio.run(answer_question(db, f'Summarize report #{own.id}', user=other))
        assert 'Food and water needed' in summary['answer'] and summary['mode'] == 'local_summary'
        assert 'Food and water needed' not in denied['answer']
        help = asyncio.run(answer_question(db, 'How do I submit a report?', user=citizen))
        assert 'New report' in help['answer']


def test_agent_source_metadata_preserves_review_warning():
    sources = _extract_sources([{'tool': 'search_approved_documents_tool', 'result': {'passages': [{
        'title': 'Flood guidance', 'source_name': 'Authority', 'source_url': 'https://example.org',
        'approval_status': 'official_source_paraphrase_for_project_review', 'review_required': True, 'relevance': 0.9}]}}])
    assert sources[0]['approval_status'] == 'official_source_paraphrase_for_project_review'
    assert sources[0]['review_required'] is True
