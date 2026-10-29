from tests.test_operations_ui import operations_clients, submit
from web.app import CSRF_COOKIE


def test_attachment_htmx_upload_and_view(operations_clients):
    citizen = operations_clients['citizen']
    created = submit(citizen, '/ui/reports', message='Water rising near the school.', location='Kochi', people_affected='2', help_required='Rescue')
    incident_id = int(created.headers['HX-Redirect'].rsplit('/',1)[-1])
    path = f'/ui/incidents/{incident_id}/attachments'
    response = citizen.get(path, headers={'HX-Request':'true'})
    assert response.status_code == 200 and 'Add photo or voice recording' in response.text
    image = b'\x89PNG\r\n\x1a\n' + b'synthetic'
    uploaded = citizen.post(path, headers={'HX-Request':'true'}, data={'_csrf':citizen.cookies.get(CSRF_COOKIE)}, files={'file':('report.png',image,'image/png')})
    assert uploaded.status_code == 200, uploaded.text
    assert 'report.png' in uploaded.text and 'data:image/png;base64,' in uploaded.text
    assert operations_clients['admin'].get(path, headers={'HX-Request':'true'}).status_code == 200
