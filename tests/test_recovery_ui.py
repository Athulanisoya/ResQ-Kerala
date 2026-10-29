from tests.test_operations_ui import operations_clients
from backend.routers import recovery
from web.app import CSRF_COOKIE


def test_unauthenticated_recovery_form_csrf_and_reset(operations_clients, monkeypatch):
    client = operations_clients['citizen']
    client.headers.pop('Authorization')
    class Configured:
        def available(self): return True
    tokens = []
    monkeypatch.setattr(recovery, 'RecoveryConfig', Configured)
    monkeypatch.setattr(recovery, 'send_recovery_email', lambda config,email,token: tokens.append(token))
    page = client.get('/forgot-password')
    assert page.status_code == 200 and 'Recover your password' in page.text
    assert client.post('/ui/forgot-password', data={'email':'citizen@operations.example'}).status_code == 403
    request = client.post('/ui/forgot-password', headers={'HX-Request':'true'}, data={'_csrf':client.cookies.get(CSRF_COOKIE),'email':'citizen@operations.example'})
    assert request.status_code == 200 and 'Check your email' in request.text and len(tokens) == 1
    page = client.get('/reset-password')
    assert 'recovery-token' in page.text and 'recovery.js' in page.text
    result = client.post('/ui/reset-password', headers={'HX-Request':'true'}, data={'_csrf':client.cookies.get(CSRF_COOKIE),'token':tokens[0],'password':'new-secure-password','confirm':'new-secure-password'})
    assert result.status_code == 200 and 'Password updated' in result.text
