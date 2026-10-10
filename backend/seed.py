"""Provision local demonstration accounts for the three roles, without public role selection."""
import json
import secrets

from sqlalchemy import select

from .config import WORKSPACE_ROOT
from .database.connection import SessionLocal, initialize_database
from .models import Role, User
from .utils.security import hash_password


def seed():
    initialize_database()
    destination = WORKSPACE_ROOT / ".runtime" / "demo-accounts.json"
    previous = json.loads(destination.read_text()) if destination.exists() else None
    password = previous["password"] if previous else secrets.token_urlsafe(20)
    accounts = [
        {"email": "citizen@athul.example.com", "full_name": "Demo Citizen", "role": Role.CITIZEN},
        {"email": "admin@athul.example.com", "full_name": "Demo Admin", "role": Role.ADMIN},
        {"email": "team@athul.example.com", "full_name": "Demo Response Team", "role": Role.RESPONSE_TEAM},
    ]
    created = []
    with SessionLocal() as db:
        for data in accounts:
            user = db.scalar(select(User).where(User.email == data["email"]))
            if user is None:
                db.add(User(**data, password_hash=hash_password(password)))
                created.append(data["email"])
        db.commit()
    if created or not previous:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps({"password": password, "accounts": [{**data, "role": data["role"].value, "uses_shared_password": data["email"] in created or bool(previous)} for data in accounts]}, indent=2), encoding="utf-8")
    print(f"Authentication demo ready; created {len(created)} account(s). Local details: .runtime/demo-accounts.json")


if __name__ == "__main__":
    seed()
