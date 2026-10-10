from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import TokenSession, User


TOKEN_ISSUER = "resq-athul-week1"
TOKEN_AUDIENCE = "resq-athul-week1"


def unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Your session is invalid or expired. Please sign in again.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def create_session_token(db: Session, user: User) -> str:
    settings = get_settings()
    issued_at = datetime.now(timezone.utc)
    expires_at = issued_at + timedelta(minutes=settings.jwt_expire_minutes)
    session_id = str(uuid4())
    db.add(TokenSession(id=session_id, user_id=user.id, expires_at=expires_at))
    return jwt.encode(
        {"sub": str(user.id), "sid": session_id, "iat": issued_at, "exp": expires_at,
         "iss": TOKEN_ISSUER, "aud": TOKEN_AUDIENCE},
        settings.jwt_secret.get_secret_value(), algorithm="HS256",
    )


def decode_session_token(token: str) -> dict:
    try:
        payload = jwt.decode(
            token, get_settings().jwt_secret.get_secret_value(), algorithms=["HS256"],
            audience=TOKEN_AUDIENCE, issuer=TOKEN_ISSUER,
            options={"require": ["sub", "sid", "iat", "exp", "iss", "aud"]},
        )
        if not isinstance(payload["sub"], str) or not payload["sub"].isdigit():
            raise unauthorized()
        if not isinstance(payload["sid"], str) or len(payload["sid"]) != 36:
            raise unauthorized()
        return payload
    except jwt.InvalidTokenError:
        raise unauthorized() from None
