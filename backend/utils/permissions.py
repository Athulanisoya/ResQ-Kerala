from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from ..database.connection import get_db
from ..models import Role, TokenSession, User
from .jwt import decode_session_token, unauthorized


bearer = HTTPBearer(auto_error=False)


@dataclass
class Principal:
    user: User
    session: TokenSession


def get_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> Principal:
    if credentials is None:
        raise unauthorized()
    payload = decode_session_token(credentials.credentials)
    token_session = db.get(TokenSession, payload["sid"])
    if token_session is None or token_session.revoked_at is not None:
        raise unauthorized()
    expiry = token_session.expires_at
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    if expiry <= datetime.now(timezone.utc) or token_session.user_id != int(payload["sub"]):
        raise unauthorized()
    user = db.get(User, token_session.user_id)
    if user is None or not user.active:
        raise unauthorized()
    return Principal(user=user, session=token_session)


def get_current_user(principal: Principal = Depends(get_principal)) -> User:
    return principal.user


def require_roles(*roles: Role):
    def permission(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="You do not have permission for this action.")
        return user
    return permission

def require_incident_access(
    db,
    incident_id,
    user,
    lock=False,
):
    from sqlalchemy import select

    from backend.models import Incident

    query = select(Incident).where(
        Incident.id == incident_id
    )

    if lock:
        query = query.with_for_update()

    incident = db.scalar(query)

    if incident is None:
        raise HTTPException(
            404,
            "Incident not found",
        )

    owner = (
        user.role == Role.CITIZEN
        and incident.user_id == user.id
    )

    assigned = (
        user.role == Role.RESPONSE_TEAM
        and user.team_id is not None
        and incident.assigned_team_id == user.team_id
    )

    if not (
        user.role == Role.ADMIN
        or owner
        or assigned
    ):
        raise HTTPException(
            403,
            "This incident is outside your access",
        )

    return incident


def require_assigned_service_team(
    db,
    incident,
    user,
    team_types,
):
    from backend.models import Team

    if (
        user.role != Role.RESPONSE_TEAM
        or user.team_id is None
        or incident.assigned_team_id != user.team_id
    ):
        raise HTTPException(
            403,
            "Only the assigned response team can perform this action",
        )

    team = db.get(Team, user.team_id)

    if (
        team is None
        or team.team_type.casefold() not in team_types
    ):
        raise HTTPException(
            403,
            "This action needs the appropriate service team type",
        )

    return team