from sqlalchemy.orm import Session
from backend.models.team import Team


def get_available_teams(db: Session):
    return (
        db.query(Team)
        .filter(Team.status == "AVAILABLE")
        .all()
    )


def get_team_by_id(db: Session, team_id: int):
    return (
        db.query(Team)
        .filter(Team.id == team_id)
        .first()
    )
def assign_team(db: Session, team_id: int):
    team = get_team_by_id(db, team_id)

    if team is None:
        return None

    if team.status != "AVAILABLE":
        return None

    team.status = "BUSY"
    db.commit()
    db.refresh(team)

    return team