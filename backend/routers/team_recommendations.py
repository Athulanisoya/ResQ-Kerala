"""Administrator-only area declarations and human-reviewed team candidates."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.database.connection import get_db
from backend.models import Role, User
from backend.schemas.team_coverage_schema import Capability, TeamCoverageUpdate, TeamType
from backend.services import team_recommendation_service as service
from backend.utils.permissions import require_roles


router = APIRouter(prefix="/api/admin", tags=["Team recommendations"])
admin = require_roles(Role.ADMIN)


@router.get("/team-coverage/catalog")
def catalog(_actor: User = Depends(admin)):
    return service.coverage_catalog()


@router.get("/teams/{team_id}/coverage")
def coverage(team_id: int, db: Session = Depends(get_db), _actor: User = Depends(admin)):
    return service.coverage_payload(db, team_id)


@router.put("/teams/{team_id}/coverage")
def update(team_id: int, data: TeamCoverageUpdate, db: Session = Depends(get_db), actor: User = Depends(admin)):
    return service.update_coverage(db, team_id, actor, data)


@router.get("/incidents/{incident_id}/team-recommendations")
def recommendations(incident_id: int, team_type: TeamType = "Rescue", capability: Capability | None = None,
                    db: Session = Depends(get_db), _actor: User = Depends(admin)):
    return service.recommendations(db, incident_id, team_type=team_type, capability=capability)
