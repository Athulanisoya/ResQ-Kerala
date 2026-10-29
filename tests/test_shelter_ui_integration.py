"""Shelter and assistant session/UI integration checks."""
from tests.test_web import clients, login, post


def test_shelters_assistant_bootstrap_and_forms(clients):
    citizen, _, _ = clients
    login(citizen, 'citizen')
    dashboard = citizen.get('/dashboard')
    assert 'href="/shelters"' in dashboard.text
    assert 'href="/assistant"' in dashboard.text
    for path in ('/shelters', '/assistant'):
        shell = citizen.get(path, headers={'X-ResQ-Page': ''})
        assert shell.status_code == 200 and 'data-session-bootstrap' in shell.text
        fragment = citizen.get(path, headers={'HX-Request': 'true'})
        assert fragment.status_code == 200
        assert 'hx-get="/shelters"' in fragment.text if path == '/shelters' else 'hx-post="/ui/assistant/chat"' in fragment.text


def test_assistant_status_form_uses_authenticated_session(clients):
    citizen, _, _ = clients
    login(citizen, 'citizen')
    response = post(citizen, '/ui/assistant/chat', question='What is the status of my report?')
    assert response.status_code == 200
    assert 'No accessible report matched' in response.text
