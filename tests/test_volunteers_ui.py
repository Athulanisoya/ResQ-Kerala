from test_session_ui import session_ui, session_ui_password_hash
from backend.models import Role


def test_volunteer_screens_require_role_and_preserve_theme(session_ui):
    page = session_ui.client.get('/volunteers', headers=session_ui.headers(Role.CITIZEN))
    assert page.status_code == 200
    assert 'Your volunteer application' in page.text and 'My application' in page.text
    assert 'volunteers.css' in page.text and 'coast-canopy.css' in page.text
    admin = session_ui.client.get('/volunteers?tab=applications', headers=session_ui.headers(Role.ADMIN))
    assert admin.status_code == 200 and 'Application review' in admin.text
    assert session_ui.client.get('/volunteers', headers=session_ui.headers(Role.RESPONSE_TEAM)).status_code == 403
    shell = session_ui.client.get('/volunteers')
    assert 'data-session-bootstrap' in shell.text and 'Your volunteer application' not in shell.text
