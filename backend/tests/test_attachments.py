from backend.tests.test_auth import api, synthetic_password_hash
from backend.tests.test_workflows import workflow, submit


def test_attachment_is_private_bounded_and_owner_only(workflow):
    api = workflow
    report_id = submit(api).json()['id']
    url = f'/api/incidents/{report_id}/attachments'
    citizen, admin, other = api.headers('citizen'), api.headers('admin'), api.headers('other_citizen')
    image = b'\x89PNG\r\n\x1a\n' + b'synthetic'
    response = api.client.post(url, headers=citizen, files={'file': ('../../proof.png', image, 'image/png')})
    assert response.status_code == 201, response.text
    attachment = response.json()
    assert attachment['filename'] == 'proof.png'
    assert attachment['media_type'] == 'image/png'
    assert api.client.get(url, headers=admin).status_code == 200
    assert api.client.get(url, headers=other).status_code == 403
    assert api.client.get(f'{url}/{attachment["id"]}', headers=other).status_code == 403
    assert api.client.post(url, headers=admin, files={'file': ('photo.png', image, 'image/png')}).status_code == 403
    assert api.client.post(url, headers=citizen, files={'file': ('fake.png', b'<svg></svg>', 'image/png')}).status_code == 422
    assert api.client.post(url, headers=citizen, files={'file': ('large.png', image + b'x' * (3 * 1024 * 1024), 'image/png')}).status_code == 422
    audio = b'RIFF' + b'0000' + b'WAVE' + b'synthetic'
    assert api.client.post(url, headers=citizen, files={'file': ('voice.wav', audio, 'audio/wav')}).status_code == 201
    assert len(api.client.get(url, headers=citizen).json()) == 2


def test_cancelled_report_rejects_new_media(workflow):
    from backend.models import Incident
    api = workflow
    report_id = submit(api).json()['id']
    with api.sessions() as db:
        db.get(Incident, report_id).status = 'CANCELLED'
        db.commit()
    image = b'\x89PNG\r\n\x1a\n' + b'synthetic'
    response = api.client.post(f'/api/incidents/{report_id}/attachments', headers=api.headers('citizen'), files={'file':('proof.png',image,'image/png')})
    assert response.status_code == 409


def test_investigator_can_view_only_own_assignment_media(workflow):
    from fastapi.testclient import TestClient
    from backend.models import Team
    from backend.models.investigation import InvestigationReport, InvestigationTeamAssignment
    from web.app import app as web_app
    api = workflow
    first = submit(api).json()['id']
    second = submit(api, message='A different incident needs urgent assistance.').json()['id']
    image = b'\x89PNG\r\n\x1a\n' + b'synthetic'
    for incident_id in (first, second):
        assert api.client.post(f'/api/incidents/{incident_id}/attachments', headers=api.headers('citizen'), files={'file':('proof.png',image,'image/png')}).status_code == 201
    with api.sessions() as db:
        db.get(Team, api.other_team_id).team_type = 'Investigation'
        report = InvestigationReport(incident_id=first, assigned_to_name='Investigator', status='IN_PROGRESS', created_by_user_id=api.users['admin'], updated_by_user_id=api.users['admin'])
        db.add(report); db.flush()
        db.add(InvestigationTeamAssignment(investigation_id=report.id, team_id=api.other_team_id, assigned_by_user_id=api.users['admin']))
        db.commit()
    investigator = api.headers('other_team')
    assert api.client.get(f'/api/incidents/{first}/attachments',headers=investigator).status_code == 200
    assert api.client.get(f'/api/incidents/{second}/attachments',headers=investigator).status_code == 403
    assert api.client.post(f'/api/incidents/{first}/attachments',headers=investigator,files={'file':('proof.png',image,'image/png')}).status_code == 403
    with TestClient(web_app) as client:
        result = client.get(f'/ui/incidents/{first}/attachments',headers={**investigator,'HX-Request':'true'})
        assert result.status_code == 200 and 'data:image/png;base64,' in result.text
        assert 'Add photo or voice recording' not in result.text
        assert client.get(f'/ui/incidents/{second}/attachments',headers={**investigator,'HX-Request':'true'}).status_code == 403


def test_both_http_stacks_reject_oversized_upload_before_parsing(workflow):
    from fastapi.testclient import TestClient
    from web.app import app as web_app
    from backend.utils.attachment_limits import _MAX_REQUEST_BYTES
    api = workflow
    report_id = submit(api).json()['id']
    body = b'x' * (_MAX_REQUEST_BYTES + 1)
    result = api.client.post(f'/api/incidents/{report_id}/attachments', headers=api.headers('citizen'), content=body)
    assert result.status_code == 413
    with TestClient(web_app) as client:
        result = client.post(f'/ui/incidents/{report_id}/attachments', headers=api.headers('citizen'), content=body)
        assert result.status_code == 413
