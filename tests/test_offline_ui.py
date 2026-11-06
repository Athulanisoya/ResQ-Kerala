"""Public offline shell never contains a user's authenticated workspace."""
from uuid import uuid4

from test_session_ui import session_ui, session_ui_password_hash
from backend.models import Role


def test_public_offline_shell_and_worker_have_no_account_details(session_ui):
    shell = session_ui.client.get('/offline/report-form')
    assert shell.status_code == 200
    assert 'data-offline-shell' in shell.text
    assert 'data-offline-form' in shell.text
    assert '<h1>Report an incident</h1>' in shell.text
    assert 'Drafts and waiting reports' in shell.text
    assert 'Open offline reporter' not in shell.text
    assert 'href="/offline-report"' not in shell.text
    for user in session_ui.users.values():
        assert user['email'] not in shell.text
    assert shell.headers['cache-control'] == 'no-store'
    worker = session_ui.client.get('/offline-worker.js')
    assert worker.status_code == 200
    assert worker.headers['service-worker-allowed'] == '/'
    assert "request.headers.has('Authorization')" in worker.text
    assert "'/api/" not in worker.text
    assert "'/dashboard'" not in worker.text


def test_citizen_form_and_local_queue_controls(session_ui):
    page = session_ui.client.get('/reports/new', headers=session_ui.headers(Role.CITIZEN))
    assert page.status_code == 200
    assert 'data-offline-form' in page.text
    assert 'Save draft</button>' in page.text
    assert '<span>Offline drafts</span>' not in page.text
    assert 'href="/offline-report"' not in page.text
    assert page.text.index('data-offline-panel') < page.text.index('<aside class="form-aside">')
    assert 'data-offline-records' in page.text
    assert f'data-user-id="{session_ui.users[Role.CITIZEN]["id"]}"' in page.text


def test_web_form_can_replay_a_submission_key(session_ui):
    values = {'location': 'Aluva', 'message': 'Synthetic retry test: floodwater near the bridge.',
              'client_submission_id': str(uuid4())}
    first = session_ui.post('/ui/reports', Role.CITIZEN, **values)
    second = session_ui.post('/ui/reports', Role.CITIZEN, **values)
    assert first.status_code == second.status_code == 200
    assert first.headers['HX-Redirect'] == second.headers['HX-Redirect']


def test_old_offline_bookmark_redirects_to_normal_reporting(session_ui):
    response = session_ui.client.get('/offline-report')
    assert response.status_code == 303
    assert response.headers['location'] == '/reports/new'
