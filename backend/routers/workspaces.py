"""Small real endpoints to demonstrate role permissions without other members' modules."""
from fastapi import APIRouter, Depends

from ..models import Role, User
from ..utils.permissions import require_roles

router = APIRouter(prefix="/api/workspaces", tags=["Role access demonstration"])


def workspace(role: Role, title: str):
    return {"role": role.value, "title": title, "message": "Your role is authorized to open this workspace. This module demonstrates authentication and permissions only."}


@router.get("/citizen")
def citizen_workspace(_user: User = Depends(require_roles(Role.CITIZEN))):
    return workspace(Role.CITIZEN, "Citizen workspace")


@router.get("/admin")
def admin_workspace(_user: User = Depends(require_roles(Role.ADMIN))):
    return workspace(Role.ADMIN, "Admin workspace")


@router.get("/response-team")
def response_team_workspace(_user: User = Depends(require_roles(Role.RESPONSE_TEAM))):
    return workspace(Role.RESPONSE_TEAM, "Response team workspace")
