"""Week 1 admin report review and manual team assignment only."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database.connection import get_db
from ..models import Incident, Role, User
from ..schemas.incident_schema import IncidentResponse, TeamAssignment
from ..services.incident_service import assign_team
from ..utils.permissions import require_roles


router = APIRouter(prefix="/api/admin", tags=["Admin"])


@router.get("/incidents", response_model=list[IncidentResponse])
def all_incidents(db: Session = Depends(get_db),
                  _user: User = Depends(require_roles(Role.ADMIN))):
    return db.query(Incident).order_by(Incident.created_at.desc(), Incident.id.desc()).all()


@router.post("/assign-team", response_model=IncidentResponse)
def assign_response_team(data: TeamAssignment, db: Session = Depends(get_db),
                         _user: User = Depends(require_roles(Role.ADMIN))):
    return assign_team(db, data.incident_id, data.team_id)
