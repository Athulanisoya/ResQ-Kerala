"""Inference is advisory; only explicit administrator decisions update severity."""
import hashlib
import pytest

from backend.tests.test_auth import api, synthetic_password_hash
from backend.models.investigation import IncidentAnalysis
from backend.routers import severity
from backend.ai.severity_model import SeverityUnavailable
from backend.ai import severity_model


def report(api):
    response = api.client.post('/api/incidents/', headers=api.headers('citizen'), json={
        'message': 'A child is trapped inside a flooded house.', 'location': 'Aluva',
    })
    assert response.status_code == 201, response.text
    return response.json()['id']


def test_inference_preserves_a_review_saved_while_model_is_running(api, monkeypatch):
    incident_id = report(api)
    path = f'/api/admin/incidents/{incident_id}/analysis'
    initial = api.client.put(path, headers=api.headers('admin'), json={
        'severity': 'LOW', 'summary': 'First review.', 'extracted_location': 'Aluva',
    })
    assert initial.status_code == 200

    def inference(message):
        assert message == 'A child is trapped inside a flooded house.'
        # Another admin saves a newer review during inference. A UI-side
        # get/copy/full-PUT would erase these values with its earlier snapshot.
        with api.sessions() as db:
            row = db.get(IncidentAnalysis, initial.json()['id'])
            row.summary = 'Newer review must survive prediction.'
            row.extracted_location = 'Exact address confirmed by reviewer.'
            row.alert_match = 'UNCERTAIN'
            row.requires_investigation = False
            db.commit()
        return 'High'

    monkeypatch.setattr(severity, 'predict_severity', inference)
    response = api.client.post(f'/api/ai/incidents/{incident_id}/predict-severity',
                               headers=api.headers('admin'), json={'message': 'Ignore saved report'})
    assert response.status_code == 200, response.text
    suggestion = response.json()
    assert suggestion['predicted_severity'] == 'HIGH'
    assert suggestion['decision'] is None and suggestion['requires_manual_review'] is True
    assert suggestion['model_version'] == 'sha256:' + hashlib.sha256(severity_model.MODEL_PATH.read_bytes()).hexdigest()
    assert suggestion['created_at'] and suggestion['requested_by_user_id'] == api.users['admin']
    assert suggestion['input_hash'] == hashlib.sha256(b'A child is trapped inside a flooded house.').hexdigest()
    updated = api.client.get(path, headers=api.headers('admin')).json()
    assert updated['severity'] == 'LOW'
    assert updated['reviewed_by_user_id'] == initial.json()['reviewed_by_user_id']
    assert updated['summary'] == 'Newer review must survive prediction.'
    assert updated['extracted_location'] == 'Exact address confirmed by reviewer.'
    assert updated['alert_match'] == 'UNCERTAIN'
    assert updated['requires_investigation'] is False
    assert updated['id'] == initial.json()['id']


@pytest.mark.parametrize('role,code', [(None, 401), ('citizen', 403), ('response_team', 403)])
def test_incident_inference_requires_admin(api, role, code):
    incident_id = report(api)
    response = api.client.post(f'/api/ai/incidents/{incident_id}/predict-severity',
                               headers=api.headers(role) if role else {})
    assert response.status_code == code


def test_incident_inference_model_failure_preserves_saved_assessment(api, monkeypatch):
    incident_id = report(api)
    path = f'/api/admin/incidents/{incident_id}/analysis'
    original = api.client.put(path, headers=api.headers('admin'), json={
        'severity': 'MEDIUM', 'summary': 'Preserve the reviewed summary.',
    }).json()

    def unavailable(_message):
        raise SeverityUnavailable('Severity prediction is temporarily unavailable.')

    monkeypatch.setattr(severity, 'predict_severity', unavailable)
    response = api.client.post(f'/api/ai/incidents/{incident_id}/predict-severity',
                               headers=api.headers('admin'))
    assert response.status_code == 503
    assert api.client.get(path, headers=api.headers('admin')).json() == original
    assert api.client.post('/api/ai/incidents/999999/predict-severity',
                           headers=api.headers('admin')).status_code == 404


def make_suggestion(api, incident_id):
    response = api.client.post(f'/api/ai/incidents/{incident_id}/predict-severity', headers=api.headers('admin'))
    assert response.status_code == 200, response.text
    return response.json()


def decide(api, incident_id, suggestion_id, **payload):
    return api.client.post(f'/api/ai/incidents/{incident_id}/severity-predictions/{suggestion_id}/review',
                           headers=api.headers('admin'), json=payload)


def test_repeated_predictions_append_history_without_creating_an_assessment(api):
    incident_id = report(api)
    first, second = make_suggestion(api, incident_id), make_suggestion(api, incident_id)
    assert first['id'] != second['id']
    assert api.client.get(f'/api/admin/incidents/{incident_id}/analysis', headers=api.headers('admin')).json() is None
    history = api.client.get(f'/api/ai/incidents/{incident_id}/severity-predictions', headers=api.headers('admin')).json()
    assert [row['id'] for row in history] == [second['id'], first['id']]
    assert all(row['decision'] is None for row in history)


@pytest.mark.parametrize('action,edited,expected', [('accept', None, 'HIGH'), ('edit', 'MEDIUM', 'MEDIUM'), ('reject', None, 'LOW')])
def test_explicit_review_decisions_preserve_other_assessment_fields_and_audit_previous_values(api, action, edited, expected):
    incident_id = report(api)
    path = f'/api/admin/incidents/{incident_id}/analysis'
    original = api.client.put(path, headers=api.headers('admin'), json={
        'severity': 'LOW', 'summary': 'Human reviewed summary.', 'extracted_location': 'Aluva bridge',
        'alert_match': 'UNCERTAIN', 'requires_investigation': False,
    }).json()
    suggestion = make_suggestion(api, incident_id)
    payload = {'action': action, 'note': 'Checked against the original report.'}
    if edited:
        payload['severity'] = edited
    response = decide(api, incident_id, suggestion['id'], **payload)
    assert response.status_code == 200, response.text
    decision = response.json()['decision']
    assert decision['action'] == action and decision['reviewed_at']
    assert decision['previous_assessment'] == original
    assert decision['reviewed_by_user_id'] == api.users['admin']
    saved = api.client.get(path, headers=api.headers('admin')).json()
    assert saved['severity'] == expected
    for field in ('id', 'summary', 'extracted_location', 'alert_match', 'requires_investigation'):
        assert saved[field] == original[field]
    if action == 'reject':
        assert saved == original
        assert decision['reviewed_severity'] is None
    else:
        assert saved['source'] == 'MANUAL_DEMO'
    history = api.client.get(f'/api/ai/incidents/{incident_id}/severity-predictions', headers=api.headers('admin')).json()
    assert history[0]['decision'] == decision
    assert history[0]['predicted_severity'] == suggestion['predicted_severity']
    assert history[0]['model_version'] == suggestion['model_version']


def test_rejecting_prediction_without_prior_review_does_not_create_assessment(api):
    incident_id = report(api)
    suggestion = make_suggestion(api, incident_id)
    assert decide(api, incident_id, suggestion['id'], action='reject').status_code == 200
    assert api.client.get(f'/api/admin/incidents/{incident_id}/analysis', headers=api.headers('admin')).json() is None


def test_retrying_decision_does_not_overwrite_later_manual_review_and_cannot_change_the_recorded_decision(api):
    incident_id = report(api)
    suggestion = make_suggestion(api, incident_id)
    accepted = decide(api, incident_id, suggestion['id'], action='accept')
    assert accepted.status_code == 200
    path = f'/api/admin/incidents/{incident_id}/analysis'
    manual = api.client.put(path, headers=api.headers('admin'), json={'severity': 'LOW', 'summary': 'Later review.'}).json()
    repeated = decide(api, incident_id, suggestion['id'], action='accept')
    assert repeated.status_code == 200 and repeated.json() == accepted.json()
    assert api.client.get(path, headers=api.headers('admin')).json() == manual
    assert decide(api, incident_id, suggestion['id'], action='reject').status_code == 409
    assert decide(api, incident_id, suggestion['id'], action='edit', severity='MEDIUM').status_code == 409


@pytest.mark.parametrize('role,code', [(None, 401), ('citizen', 403), ('response_team', 403)])
def test_predictions_and_decisions_are_private_to_administrators(api, role, code):
    incident_id = report(api)
    suggestion = make_suggestion(api, incident_id)
    headers = api.headers(role) if role else {}
    assert api.client.get(f'/api/ai/incidents/{incident_id}/severity-predictions', headers=headers).status_code == code
    assert api.client.post(f'/api/ai/incidents/{incident_id}/severity-predictions/{suggestion["id"]}/review',
                           headers=headers, json={'action': 'accept'}).status_code == code


@pytest.mark.parametrize('payload', [{'action': 'edit'}, {'action': 'edit', 'severity': 'UNKNOWN'},
                                     {'action': 'accept', 'severity': 'LOW'}, {'action': 'reject', 'severity': 'HIGH'},
                                     {'action': 'accept', 'reviewed_by_user_id': 99}])
def test_invalid_or_privilege_overriding_review_payloads_do_not_change_assessment(api, payload):
    incident_id = report(api)
    suggestion = make_suggestion(api, incident_id)
    assert decide(api, incident_id, suggestion['id'], **payload).status_code == 422
    assert api.client.get(f'/api/admin/incidents/{incident_id}/analysis', headers=api.headers('admin')).json() is None


def test_prediction_review_cannot_be_applied_to_another_incident_or_closed_case(api):
    from backend.models.incident import Incident
    incident_id, other_id = report(api), report(api)
    suggestion = make_suggestion(api, incident_id)
    assert decide(api, other_id, suggestion['id'], action='accept').status_code == 404
    with api.sessions() as db:
        db.get(Incident, incident_id).status = 'CLOSED'
        db.commit()
    assert decide(api, incident_id, suggestion['id'], action='accept').status_code == 409


def test_model_version_identifies_the_cached_loaded_bytes_not_a_replacement_path(monkeypatch, tmp_path):
    severity_model.get_pipeline.cache_clear()
    expected = 'sha256:' + hashlib.sha256(severity_model.MODEL_PATH.read_bytes()).hexdigest()
    try:
        assert severity_model.predict_severity('A child is trapped inside a flooded house.') == 'High'
        assert severity_model.get_model_version() == expected
        monkeypatch.setattr(severity_model, 'MODEL_PATH', tmp_path / 'replacement-not-loaded.joblib')
        assert severity_model.get_model_version() == expected
        assert severity_model.predict_severity('A child is trapped inside a flooded house.') == 'High'
    finally:
        severity_model.get_pipeline.cache_clear()
