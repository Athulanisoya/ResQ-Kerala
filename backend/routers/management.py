"""Administrator-only account, team, and aggregate reporting endpoints."""
from datetime import datetime, timezone
import json
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session
from backend.database.connection import get_db
from backend.models import Incident, Role, Team, TokenSession, User
from backend.models.admin_audit import AdminChange
from backend.models.community import DonationCampaign, DonationPledge
from backend.models.investigation import InvestigationReport, InvestigationTeamAssignment
from backend.models.operations import ReliefRequest as OperationsRequest
from backend.models.relief import ReliefRequest as VidyaRequest
from backend.models.shelter import Shelter
from backend.utils.permissions import require_roles

router = APIRouter(prefix="/api/management", tags=["Administration"])
admin = require_roles(Role.ADMIN)

class UserChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Role
    team_id: int | None = Field(default=None, gt=0)
    active: bool
    @model_validator(mode="after")
    def validate_membership(self):
        if self.role == Role.RESPONSE_TEAM and self.active and self.team_id is None:
            raise ValueError("A response team account must have a team")
        if self.role != Role.RESPONSE_TEAM and self.team_id is not None:
            raise ValueError("Only response team accounts can have a team")
        return self

class TeamCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=2, max_length=100)
    team_type: Literal["Rescue", "Relief", "Shelter", "Investigation"]

class TeamChange(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=2, max_length=100)
    status: Literal["AVAILABLE", "OFFLINE"]

def _user(row):
    return {"id": row.id, "full_name": row.full_name, "email": row.email,
            "role": row.role.value, "team_id": row.team_id, "active": row.active}

def _team(row):
    return {"id": row.id, "name": row.name, "team_type": row.team_type, "status": row.status}

def _record(db, actor, kind, target, action, changes):
    db.add(AdminChange(actor_id=actor.id, target_kind=kind, target_id=target.id,
                       action=action, details=json.dumps(changes, sort_keys=True)))

def _lock_admins(db, actor):
    # Serialize role/deactivation changes across all administrators, and refresh
    # the caller after locks so concurrent demotions cannot authorize a write.
    admins = list(db.scalars(select(User).where(User.role == Role.ADMIN)
                            .order_by(User.id).with_for_update(key_share=True).execution_options(populate_existing=True)))
    current = next((item for item in admins if item.id == actor.id), None)
    if current is None or not current.active:
        raise HTTPException(403, "An active administrator is required")
    return admins

@router.get("/users")
def users(db: Session = Depends(get_db), actor: User = Depends(admin)):
    return [_user(row) for row in db.scalars(select(User).order_by(User.id))]

@router.patch("/users/{user_id}")
def change_user(user_id: int, data: UserChange, db: Session = Depends(get_db), actor: User = Depends(admin)):
    admins = _lock_admins(db, actor)
    target = db.scalar(select(User).where(User.id == user_id).with_for_update().execution_options(populate_existing=True))
    if target is None:
        raise HTTPException(404, "Account not found")
    if target.id == actor.id and (not data.active or data.role != Role.ADMIN):
        raise HTTPException(409, "You cannot deactivate or demote your own administrator account")
    if target.role == Role.ADMIN and target.active and (not data.active or data.role != Role.ADMIN):
        if sum(1 for item in admins if item.active) <= 1:
            raise HTTPException(409, "At least one active administrator is required")
    if data.team_id is not None:
        team = db.scalar(select(Team).where(Team.id == data.team_id).with_for_update())
        if team is None:
            raise HTTPException(404, "Team not found")
        if team.status == "OFFLINE" and data.active:
            raise HTTPException(409, "Select an active team for this account")
    before = _user(target)
    target.role, target.team_id, target.active = data.role, data.team_id, data.active
    after = _user(target)
    if before != after:
        # Force a new sign-in after privilege, team or activation changes.
        db.execute(update(TokenSession).where(TokenSession.user_id == target.id,
                   TokenSession.revoked_at.is_(None)).values(revoked_at=datetime.now(timezone.utc)))
        _record(db, actor, "user", target, "update", {"before": before, "after": after})
    db.commit()
    return after

@router.get("/teams")
def list_teams(db: Session = Depends(get_db), actor: User = Depends(admin)):
    return [_team(row) for row in db.scalars(select(Team).order_by(Team.name, Team.id))]

@router.post("/teams", status_code=201)
def create_team(data: TeamCreate, db: Session = Depends(get_db), actor: User = Depends(admin)):
    _lock_admins(db, actor)
    if db.scalar(select(Team.id).where(func.lower(Team.name) == data.name.lower()).limit(1)) is not None:
        raise HTTPException(409, "A team with this name already exists")
    team = Team(name=data.name, team_type=data.team_type, status="AVAILABLE")
    db.add(team); db.flush(); _record(db, actor, "team", team, "create", _team(team)); db.commit()
    return _team(team)

@router.patch("/teams/{team_id}")
def change_team(team_id: int, data: TeamChange, db: Session = Depends(get_db), actor: User = Depends(admin)):
    _lock_admins(db, actor)
    team = db.scalar(select(Team).where(Team.id == team_id).with_for_update().execution_options(populate_existing=True))
    if team is None:
        raise HTTPException(404, "Team not found")
    duplicate = db.scalar(select(Team.id).where(func.lower(Team.name) == data.name.lower(), Team.id != team.id).limit(1))
    if duplicate is not None:
        raise HTTPException(409, "A team with this name already exists")
    if team.status == "BUSY":
        raise HTTPException(409, "A busy team cannot be renamed or taken offline")
    if data.status == "OFFLINE":
        active_case = db.scalar(select(Incident.id).where(Incident.assigned_team_id == team.id,
                          Incident.status.not_in(("RESOLVED", "CLOSED", "CANCELLED", "REJECTED"))).limit(1))
        active_relief = db.scalar(select(OperationsRequest.id).where(OperationsRequest.assigned_team_id == team.id,
                                   OperationsRequest.status != "COMPLETED").limit(1))
        active_investigation = db.scalar(select(InvestigationReport.id).join(InvestigationTeamAssignment,
            InvestigationTeamAssignment.investigation_id == InvestigationReport.id).where(
                InvestigationTeamAssignment.team_id == team.id,
                InvestigationReport.status.not_in(("COMPLETE", "COMPLETED"))).limit(1))
        if active_case or active_relief or active_investigation:
            raise HTTPException(409, "Finish or reassign the team's active work before taking it offline")
    before = _team(team)
    team.name, team.status = data.name, data.status
    after = _team(team)
    if before != after:
        _record(db, actor, "team", team, "update", {"before": before, "after": after})
    db.commit()
    return after

def _counts(db, column):
    return {str(key): value for key, value in db.execute(select(column, func.count()).group_by(column))}

@router.get("/reports")
def reports(db: Session = Depends(get_db), actor: User = Depends(admin)):
    """Counts preserve distinct relief ledgers and never add incompatible units."""
    donations = [{"kind": kind, "status": status, "unit": unit, "count": count, "quantity": str(quantity)}
                 for kind, status, unit, count, quantity in db.execute(select(
                     DonationPledge.kind, DonationPledge.status, DonationPledge.unit,
                     func.count(), func.sum(DonationPledge.quantity)).group_by(
                         DonationPledge.kind, DonationPledge.status, DonationPledge.unit))]
    shelter = db.execute(select(func.count(Shelter.id), func.coalesce(func.sum(Shelter.capacity), 0),
                         func.coalesce(func.sum(Shelter.occupied), 0))).one()
    vidya = [{"item": item, "requests": count, "requested": requested, "fulfilled": fulfilled}
             for item, count, requested, fulfilled in db.execute(select(VidyaRequest.item,
                 func.count(VidyaRequest.id), func.sum(VidyaRequest.quantity), func.sum(VidyaRequest.fulfilled)
             ).group_by(VidyaRequest.item))]
    return {"incidents_by_status": _counts(db, Incident.status),
            "operations_relief_by_status": _counts(db, OperationsRequest.status),
            "item_relief": vidya,
            "teams_by_status": _counts(db, Team.status),
            "shelters": {"count": shelter[0], "capacity": shelter[1], "occupied": shelter[2]},
            "shelters_by_status": _counts(db, Shelter.status),
            "campaigns_by_status": _counts(db, DonationCampaign.status), "donations": donations}
