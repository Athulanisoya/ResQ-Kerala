import json
import secrets

from sqlalchemy import select

from backend.config import WORKSPACE_ROOT

from backend.database.connection import (
    SessionLocal,
    initialize_database,
)

from backend.models import Role, Team, User
from backend.utils.security import hash_password


def seed_week3():
    initialize_database()

    destination = (
        WORKSPACE_ROOT
        / ".runtime"
        / "week3-demo-accounts.json"
    )

    records = (
        json.loads(destination.read_text())
        if destination.exists()
        else []
    )

    created = []

    with SessionLocal() as db:
        for kind in ["Relief", "Shelter"]:
            name = f"Week 3 Demo {kind} Team"

            team = db.scalar(
                select(Team).where(
                    Team.name == name
                )
            )

            if team is None:
                team = Team(
                    name=name,
                    team_type=kind,
                )

                db.add(team)

                db.flush()

            elif team.team_type.casefold() != kind.casefold():
                raise RuntimeError(
                    "Existing demo team has a different type; review it first"
                )

            email = (
                f"week3-{kind.lower()}@resq.example.com"
            )

            user = db.scalar(
                select(User).where(
                    User.email == email
                )
            )

            if user is None:
                password = secrets.token_urlsafe(20)

                user = User(
                    full_name=f"Demo {kind} Member",
                    email=email,
                    password_hash=hash_password(password),
                    role=Role.RESPONSE_TEAM,
                    team_id=team.id,
                )

                db.add(user)

                created.append(
                    {
                        "email": email,
                        "password": password,
                        "team_id": team.id,
                        "team_type": kind,
                    }
                )

            elif (
                user.role != Role.RESPONSE_TEAM
                or user.team_id != team.id
            ):
                raise RuntimeError(
                    "Existing demo account has different membership; review it first"
                )

        if created:
            destination.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            destination.write_text(
                json.dumps(
                    records + created,
                    indent=2,
                ),
                encoding="utf-8",
            )

        db.commit()

    print(
        f"Week 3 demo ready; created {len(created)} account(s)."
    )

    print(
        "Local credentials: .runtime/week3-demo-accounts.json"
    )


if __name__ == "__main__":
    seed_week3()