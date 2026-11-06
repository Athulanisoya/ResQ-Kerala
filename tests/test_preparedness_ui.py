from test_session_ui import session_ui, session_ui_password_hash
from backend.models import Role
from backend.services.preparedness_service import REVISION

def test_private_plan_form_print_and_language(session_ui):
    page = session_ui.client.get('/preparedness?lang=ml', headers=session_ui.headers(Role.CITIZEN))
    assert page.status_code == 200 and 'വീട്ടിലെ തയ്യാറെടുപ്പ് പട്ടിക' in page.text
    assert 'Print saved plan' not in page.text
    saved = session_ui.post('/ui/preparedness', Role.CITIZEN, expected_version='0', guidance_revision=REVISION,
        language='ml', nearby_meeting='<script>private-point</script>', **{'done:contacts':'true'})
    assert saved.status_code == 200 and 'Print saved plan' in saved.text and 'preparedness-print-only' in saved.text
    assert '&lt;script&gt;private-point&lt;/script&gt;' in saved.text
    assert '<script>private-point</script>' not in saved.text
    admin = session_ui.client.get('/preparedness', headers=session_ui.headers(Role.ADMIN))
    assert admin.status_code == 200 and 'private-point' not in admin.text
    assert 'private-point' not in session_ui.client.get('/preparedness').text
