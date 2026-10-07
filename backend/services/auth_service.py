from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import Role, TokenSession, User
from ..schemas.auth import AuthResponse, LoginRequest, RegisterRequest, UserResponse
from ..utils.jwt import create_session_token
from ..utils.security import dummy_password_hash, hash_password, verify_password


def auth_result(db: Session, user: User) -> AuthResponse:
    token = create_session_token(db, user)
    db.commit()
    return AuthResponse(access_token=token, user=UserResponse.model_validate(user))


def register(db: Session, data: RegisterRequest) -> AuthResponse:
    email = str(data.email).lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=409, detail="An account already exists for this email.")
    user = User(full_name=data.full_name, email=email,
                password_hash=hash_password(data.password), role=Role.CITIZEN)
    db.add(user)
    try:
        db.flush()
        return auth_result(db, user)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="An account already exists for this email.") from None


def login(db: Session, data: LoginRequest) -> AuthResponse:
    user = db.scalar(select(User).where(User.email == str(data.email).lower()))
    encoded = user.password_hash if user else dummy_password_hash
    password_valid = verify_password(data.password, encoded)
    if not user or not password_valid or not user.active:
        raise HTTPException(status_code=401, detail="Email or password is incorrect.",
                            headers={"WWW-Authenticate": "Bearer"})
    return auth_result(db, user)


def logout(db: Session, token_session: TokenSession) -> None:
    token_session.revoked_at = datetime.now(timezone.utc)
    db.commit()
