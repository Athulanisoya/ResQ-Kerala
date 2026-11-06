from test_session_ui import session_ui, session_ui_password_hash
from backend.models import Role

def test_facility_controls_and_filter_polling_context(session_ui):
    created = session_ui.client.post('/api/shelters', headers=session_ui.headers(Role.ADMIN), json={
        'name': 'Synthetic facilities UI', 'location': 'Aluva', 'capacity': 10, 'occupied': 0}).json()
    page = session_ui.client.get('/shelters?facility=wheelchair_access&facility=charging', headers=session_ui.headers(Role.CITIZEN))
    assert page.status_code == 200 and 'Required facilities' in page.text
    assert 'facility=wheelchair_access&amp;facility=charging' in page.text
    editor = session_ui.client.get(f'/ui/shelters/{created["id"]}/editor', headers=session_ui.headers(Role.ADMIN))
    assert editor.status_code == 200 and 'Confirm facility details' in editor.text
    values = dict(expected_version='0', confirmed='true', note='Synthetic inspection', wheelchair_access='YES',
                  accessible_toilets='NO', medical_support='UNKNOWN', charging='YES', pets_allowed='NO')
    saved = session_ui.post(f'/ui/shelters/{created["id"]}/facilities', Role.ADMIN, **values)
    assert saved.status_code == 200 and 'Facility details confirmed' in saved.text
    live = session_ui.client.get('/ui/shelters/live?facility=wheelchair_access&facility=charging', headers=session_ui.headers(Role.CITIZEN))
    assert live.status_code == 200 and created['name'] in live.text and 'Staff confirmed:' in live.text
