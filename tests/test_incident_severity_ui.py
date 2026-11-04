"""Classifier review is a deliberate, authenticated HTMX action."""
import re

from tests.test_web import clients, login, post


def prepare(clients):
    citizen, admin, team = clients
    login(citizen, 'citizen')
    login(admin, 'admin')
    created = citizen.post('/api/incidents/', json={
        'message': 'A child is trapped inside a flooded house.', 'location': 'Aluva',
    })
    assert created.status_code == 201
    incident_id = created.json()['id']
    original = admin.put(f'/api/admin/incidents/{incident_id}/analysis', json={
        'severity': 'LOW', 'summary': 'Saved human assessment.', 'extracted_location': 'Aluva bridge',
        'requires_investigation': False,
    }).json()
    return citizen, admin, team, incident_id, original


def test_prediction_preserves_unsaved_drafts_and_explicit_edit_updates_only_reviewed_severity(clients):
    _, admin, _, incident_id, original = prepare(clients)
    predicted = post(admin, f'/ui/reports/{incident_id}/severity', analysis_form='yes', severity='LOW',
                     summary='Unsaved manual summary.', extracted_location='Draft location',
                     alert_match='UNCERTAIN', requires_investigation='yes')
    assert predicted.status_code == 200, predicted.text
    assert 'Severity suggestion saved' in predicted.text
    assert 'Unsaved manual summary.' in predicted.text
    path = f'/api/admin/incidents/{incident_id}/analysis'
    assert admin.get(path).json() == original
    suggestions = admin.get(f'/api/ai/incidents/{incident_id}/severity-predictions').json()
    suggestion_id = suggestions[0]['id']
    assert 'Accept suggestion' in predicted.text and 'Save edited severity' in predicted.text and 'Reject suggestion' in predicted.text
    edited = post(admin, f'/ui/reports/{incident_id}/severity-suggestions/{suggestion_id}/review',
                  action='edit', reviewed_severity='MEDIUM', decision_note='Verified manually.',
                  analysis_form='yes', severity='LOW', summary='Unsaved manual summary.',
                  extracted_location='Draft location', alert_match='UNCERTAIN', requires_investigation='yes')
    assert edited.status_code == 200, edited.text
    saved = admin.get(path).json()
    assert saved['severity'] == 'MEDIUM'
    assert saved['summary'] == original['summary'] and saved['extracted_location'] == original['extracted_location']
    assert saved['requires_investigation'] is False
    assert 'Unsaved manual summary.' in edited.text
    assert re.search(r'<option value="MEDIUM"\s+selected>', edited.text)
    assert 'Verified manually.' in edited.text


def test_decision_validation_retains_note_and_requires_admin_and_csrf(clients):
    citizen, admin, team, incident_id, original = prepare(clients)
    suggestion = admin.post(f'/api/ai/incidents/{incident_id}/predict-severity').json()
    path = f'/ui/reports/{incident_id}/severity-suggestions/{suggestion["id"]}/review'
    unsafe_note = '<script>unsafe()</script>'
    invalid = post(admin, path, action='edit', reviewed_severity='unsupported', decision_note=unsafe_note)
    assert invalid.status_code == 422
    assert unsafe_note not in invalid.text and '&lt;script&gt;unsafe()&lt;/script&gt;' in invalid.text
    assert post(citizen, path, action='accept').status_code == 403
    login(team, 'response_team')
    assert post(team, path, action='accept').status_code == 403
    assert admin.post(path, headers={'HX-Request': 'true'}, data={'action': 'accept', '_csrf': 'invalid'}).status_code == 403
    assert admin.get(f'/api/admin/incidents/{incident_id}/analysis').json() == original
