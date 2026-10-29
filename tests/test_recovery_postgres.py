"""Exercise one-use reset token under real PostgreSQL row locking."""
from datetime import datetime, timedelta
import hashlib
from tests.test_operations_postgres import pg_ops, race
from backend.models.recovery import PasswordResetToken
from backend.routers.recovery import ResetPassword, reset_password


def test_concurrent_password_reset_consumes_token_once(pg_ops):
    token = 'T' * 48
    with pg_ops.sessions() as db:
        db.add(PasswordResetToken(user_id=pg_ops.users['citizen'], token_hash=hashlib.sha256(token.encode()).hexdigest(), expires_at=datetime.utcnow()+timedelta(minutes=20)))
        db.commit()
    def attempt():
        with pg_ops.sessions() as db:
            return reset_password(ResetPassword(token=token,password='new-secure-password'), db)
    results = race([attempt, attempt])
    assert sorted(code for code, _ in results) == [200, 400]


def test_request_and_reset_lock_user_before_token_without_deadlock(pg_ops, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event, current_thread
    from fastapi import HTTPException
    from sqlalchemy import event
    from backend.routers import recovery
    class Configured:
        def available(self): return True
    monkeypatch.setattr(recovery, "RecoveryConfig", Configured)
    monkeypatch.setattr(recovery, "send_recovery_email", lambda *args: None)
    old = "O" * 48
    with pg_ops.sessions() as db:
        db.add(PasswordResetToken(user_id=pg_ops.users["citizen"], token_hash=hashlib.sha256(old.encode()).hexdigest(),
                                  expires_at=datetime.utcnow() + timedelta(minutes=20)))
        db.commit()
    user_locked, token_read = Event(), Event()
    engine = pg_ops.sessions.kw["bind"]
    def observe(_conn, _cursor, statement, _params, _context, _many):
        sql = statement.lower()
        if current_thread().name == "request-recovery" and "from" in sql and "users" in sql and "for update" in sql:
            user_locked.set()
            if not token_read.wait(10):
                raise AssertionError("reset did not examine the token")
        if current_thread().name == "reset-recovery" and "select" in sql and "password_reset_tokens" in sql:
            token_read.set()
    event.listen(engine, "after_cursor_execute", observe)
    def request():
        from threading import current_thread
        current_thread().name = "request-recovery"
        with pg_ops.sessions() as db:
            return recovery.request_recovery(recovery.RequestRecovery(email="pg-citizen@example.com"), db)
    def reset():
        from threading import current_thread
        current_thread().name = "reset-recovery"
        assert user_locked.wait(10)
        with pg_ops.sessions() as db:
            try:
                recovery.reset_password(recovery.ResetPassword(token=old, password="new-secure-password"), db)
                return 200
            except HTTPException as exc:
                db.rollback(); return exc.status_code
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            request_future, reset_future = pool.submit(request), pool.submit(reset)
            assert request_future.result(timeout=30)["message"].startswith("If an active account")
            assert reset_future.result(timeout=30) == 400
    finally:
        event.remove(engine, "after_cursor_execute", observe)
