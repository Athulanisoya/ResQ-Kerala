from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database.connection import get_db
from ..models import Incident, Role, Team, User
from ..schemas.incident_schema import IncidentResponse, TeamResponse
from ..utils.permissions import require_roles


router = APIRouter(prefix="/api/teams", tags=["Response teams"])


@router.get("", response_model=list[TeamResponse])
def list_teams(db: Session = Depends(get_db),
               _user: User = Depends(require_roles(Role.ADMIN))):
    return db.query(Team).order_by(Team.name).all()


@router.get("/assignments", response_model=list[IncidentResponse])
def assigned_reports(db: Session = Depends(get_db),
                     user: User = Depends(require_roles(Role.RESPONSE_TEAM))):
    if user.team_id is None:
        return []
    return (db.query(Incident).filter(Incident.assigned_team_id == user.team_id)
            .order_by(Incident.updated_at.desc(), Incident.id.desc()).all())
