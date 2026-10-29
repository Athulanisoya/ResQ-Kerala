"""Recovery tokens are private, expiring, one-use and revoke old sessions."""
from datetime import datetime, timedelta
from sqlalchemy import select
from backend.tests.test_auth import api, synthetic_password_hash
from backend.models.recovery import PasswordResetToken
from backend.routers import recovery


def test_recovery_unconfigured_is_truthfully_unavailable(api, monkeypatch):
    class Unconfigured:
        def available(self): return False
    monkeypatch.setattr(recovery, 'RecoveryConfig', Unconfigured)
    result = api.client.post('/api/auth/recovery/request', json={'email':'missing@example.com'})
    assert result.status_code == 503
    assert 'not configured' in result.json()['detail']


def test_recovery_generic_response_one_use_and_revokes_sessions(api, monkeypatch):
    class Configured:
        def available(self): return True
    delivered = []
    monkeypatch.setattr(recovery, 'RecoveryConfig', Configured)
    monkeypatch.setattr(recovery, 'send_recovery_email', lambda config, email, token: delivered.append((email, token)))
    old_headers = api.headers('citizen')
    existing = api.client.post('/api/auth/recovery/request', json={'email':'citizen@example.com'})
    missing = api.client.post('/api/auth/recovery/request', json={'email':'no-account@example.com'})
    assert existing.status_code == missing.status_code == 202
    assert existing.json() == missing.json()
    assert len(delivered) == 1
    token = delivered[0][1]
    assert token not in existing.text
    with api.sessions() as db:
        row = db.scalar(select(PasswordResetToken))
        assert row.token_hash != token and len(row.token_hash) == 64
    result = api.client.post('/api/auth/recovery/reset', json={'token':token,'password':'Changed-pass-12345'})
    assert result.status_code == 200
    assert api.client.get('/api/users/me', headers=old_headers).status_code == 401
    assert api.client.post('/api/auth/recovery/reset', json={'token':token,'password':'Changed-pass-12345'}).status_code == 400
    login = api.client.post('/api/auth/login', json={'email':'citizen@example.com','password':'Changed-pass-12345'})
    assert login.status_code == 200


def test_expired_recovery_token_is_rejected(api, monkeypatch):
    class Configured:
        def available(self): return True
    delivered=[]
    monkeypatch.setattr(recovery, 'RecoveryConfig', Configured)
    monkeypatch.setattr(recovery, 'send_recovery_email', lambda config,email,token: delivered.append(token))
    assert api.client.post('/api/auth/recovery/request',json={'email':'citizen@example.com'}).status_code == 202
    with api.sessions() as db:
        row=db.scalar(select(PasswordResetToken)); row.expires_at=datetime.utcnow()-timedelta(seconds=1); db.commit()
    assert api.client.post('/api/auth/recovery/reset',json={'token':delivered[0],'password':'Changed-pass-12345'}).status_code == 400


def test_delivery_failure_does_not_disclose_token_and_invalidates_it(api, monkeypatch):
    class Configured:
        def available(self): return True
    monkeypatch.setattr(recovery, 'RecoveryConfig', Configured)
    def fail(*args): raise OSError('mail unavailable')
    monkeypatch.setattr(recovery, 'send_recovery_email', fail)
    response = api.client.post('/api/auth/recovery/request', json={'email':'citizen@example.com'})
    assert response.status_code == 202
    with api.sessions() as db:
        assert db.scalar(select(PasswordResetToken)).used_at is not None


def test_recovery_email_requests_are_rate_limited(api, monkeypatch):
    class Configured:
        def available(self): return True
    sent=[]
    monkeypatch.setattr(recovery, 'RecoveryConfig', Configured)
    monkeypatch.setattr(recovery, 'send_recovery_email', lambda config,email,token: sent.append(token))
    for _ in range(4):
        assert api.client.post('/api/auth/recovery/request',json={'email':'citizen@example.com'}).status_code == 202
    assert len(sent) == 3
    assert api.client.post('/api/auth/recovery/reset',json={'token':sent[0],'password':'Changed-pass-12345'}).status_code == 400
