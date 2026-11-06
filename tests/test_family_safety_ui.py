from test_session_ui import session_ui, session_ui_password_hash
from backend.models import Role

def test_family_page_and_safe_htmx_creation(session_ui):
    for role in Role:
        page = session_ui.client.get('/family-safety', headers=session_ui.headers(role))
        assert page.status_code == 200 and 'Your private circles' in page.text
    assert 'Your private circles' not in session_ui.client.get('/family-safety').text
    result = session_ui.post('/ui/family-safety', Role.CITIZEN, operation='create', name='<script>private</script>')
    assert result.status_code == 200 and '&lt;script&gt;private&lt;/script&gt;' in result.text
    assert result.headers['HX-Push-Url'] == '/family-safety?circle_id=1'
    assert '<script>private</script>' not in result.text
    admin = session_ui.client.get('/family-safety?circle_id=1', headers=session_ui.headers(Role.ADMIN))
    assert admin.status_code == 404 and 'Your check-in for this circle' not in admin.text
