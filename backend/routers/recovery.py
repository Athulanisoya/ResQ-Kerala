"""Account recovery with short-lived one-use tokens and configured SMTP."""
import hashlib
import logging
import secrets
import smtplib
import ssl
from datetime import datetime, timedelta
from email.message import EmailMessage
from functools import lru_cache
from urllib.parse import urlsplit
from fastapi import APIRouter, Depends, HTTPException
from pydantic import ConfigDict, EmailStr, Field, SecretStr, StrictStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from backend.config import WORKSPACE_ROOT
from backend.database.connection import get_db
from backend.models.recovery import PasswordResetToken
from backend.models.user import User, TokenSession
from backend.schemas.common import InputModel
from backend.utils.security import hash_password

logger = logging.getLogger(__name__)
router = APIRouter(prefix='/api/auth/recovery', tags=['Authentication'])

class RecoveryConfig(BaseSettings):
    model_config = SettingsConfigDict(env_file=WORKSPACE_ROOT / '.env', env_file_encoding='utf-8', extra='ignore')
    recovery_smtp_host: str = ''
    recovery_smtp_port: int = Field(default=587, ge=1, le=65535)
    recovery_smtp_user: str = ''
    recovery_smtp_password: SecretStr | None = None
    recovery_from_email: str = ''
    recovery_base_url: str = ''
    def available(self):
        parsed = urlsplit(self.recovery_base_url)
        origin_ok = (parsed.scheme == 'https' or (parsed.scheme == 'http' and parsed.hostname in {'localhost','127.0.0.1','::1'}))
        return bool(self.recovery_smtp_host and self.recovery_from_email and parsed.hostname and origin_ok and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment and parsed.path in {'','/'} and bool(self.recovery_smtp_user) == bool(self.recovery_smtp_password))

class RequestRecovery(InputModel):
    email: EmailStr = Field(max_length=254)

class ResetPassword(InputModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=False)
    token: StrictStr = Field(min_length=32, max_length=200)
    password: StrictStr = Field(min_length=10, max_length=128)


def send_recovery_email(config, email, token):
    message = EmailMessage()
    message['Subject'] = 'ResQ Kerala password recovery'
    message['From'] = config.recovery_from_email
    message['To'] = email
    # A URL fragment does not reach the web server or its access logs.
    link = config.recovery_base_url.rstrip('/') + '/reset-password#token=' + token
    message.set_content('Use this one-time link within 30 minutes to reset your ResQ Kerala password:\n\n' + link + '\n\nIf you did not request it, ignore this message.')
    with smtplib.SMTP(config.recovery_smtp_host, config.recovery_smtp_port, timeout=10) as smtp:
        smtp.ehlo(); smtp.starttls(context=ssl.create_default_context()); smtp.ehlo()
        if config.recovery_smtp_user:
            smtp.login(config.recovery_smtp_user, config.recovery_smtp_password.get_secret_value())
        smtp.send_message(message)

@router.post('/request', status_code=202)
def request_recovery(data: RequestRecovery, db: Session = Depends(get_db)):
    config = RecoveryConfig()
    if not config.available():
        raise HTTPException(503, 'Password recovery email is not configured. Contact an administrator.')
    email = str(data.email).strip().lower()
    user = db.scalar(select(User).where(User.email == email, User.active.is_(True)).with_for_update())
    now = datetime.utcnow()
    if user is not None:
        recent = db.scalars(select(PasswordResetToken).where(PasswordResetToken.user_id == user.id, PasswordResetToken.created_at >= now - timedelta(hours=1))).all()
        if len(recent) < 3:
            # Invalidate prior links before issuing another one.
            for old in recent:
                if old.used_at is None:
                    old.used_at = now
            token = secrets.token_urlsafe(48)
            row = PasswordResetToken(user_id=user.id, token_hash=hashlib.sha256(token.encode()).hexdigest(), expires_at=now + timedelta(minutes=30))
            db.add(row); db.commit()
            try:
                send_recovery_email(config, email, token)
            except Exception:
                # Never reveal whether an account exists, expose a token, or log credentials.
                row.used_at = datetime.utcnow(); db.commit()
                logger.warning('Password recovery delivery failed')
    return {'message': 'If an active account exists, a recovery email may arrive shortly.'}

@router.post('/reset')
def reset_password(data: ResetPassword, db: Session = Depends(get_db)):
    digest = hashlib.sha256(data.token.encode()).hexdigest()
    # Read identity first without a lock; requests and resets must both lock
    # user before token rows to avoid a lock-order inversion on PostgreSQL.
    token_identity = db.execute(select(PasswordResetToken.id, PasswordResetToken.user_id).where(
        PasswordResetToken.token_hash == digest)).first()
    if token_identity is None:
        raise HTTPException(400, 'The recovery link is invalid or expired.')
    user = db.scalar(select(User).where(User.id == token_identity.user_id).with_for_update().execution_options(populate_existing=True))
    token = db.scalar(select(PasswordResetToken).where(
        PasswordResetToken.id == token_identity.id, PasswordResetToken.user_id == token_identity.user_id,
        PasswordResetToken.token_hash == digest).with_for_update().execution_options(populate_existing=True))
    now = datetime.utcnow()
    if user is None or not user.active or token is None or token.used_at is not None or token.expires_at <= now:
        raise HTTPException(400, 'The recovery link is invalid or expired.')
    user.password_hash = hash_password(data.password)
    # Invalidate all recovery links and existing bearer sessions after reset.
    db.execute(update(PasswordResetToken).where(PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None)).values(used_at=now))
    db.execute(update(TokenSession).where(TokenSession.user_id == user.id, TokenSession.revoked_at.is_(None)).values(revoked_at=now))
    db.commit()
    return {'message': 'Password updated. Sign in again.'}
