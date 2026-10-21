"""Incident-bound inference updates only severity, including during concurrent review."""
import pytest

from backend.tests.test_auth import api, synthetic_password_hash
from backend.models.investigation import IncidentAnalysis
from backend.routers import severity
from backend.ai.severity_model import SeverityUnavailable


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
    updated = response.json()
    assert updated['severity'] == 'HIGH'
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
