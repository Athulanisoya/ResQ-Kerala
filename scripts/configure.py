"""Generate a separate local signing secret; reuse only the configured PostgreSQL connection."""
import secrets
from pathlib import Path
from dotenv import dotenv_values


root = Path(__file__).resolve().parents[1]
destination = root / ".env"
if not destination.exists():
    parent_configuration = root.parent / ".env"
    connection = dotenv_values(parent_configuration).get("DATABASE_URL") if parent_configuration.exists() else None
    if not connection:
        raise SystemExit("Copy .env.example to .env and configure PostgreSQL and a random JWT_SECRET first.")
    destination.write_text("\n".join([
        f"DATABASE_URL={connection}", "DATABASE_SCHEMA=athul_week1",
        f"JWT_SECRET={secrets.token_hex(48)}", "JWT_EXPIRE_MINUTES=30",
        "CORS_ORIGINS=http://127.0.0.1:5175,http://localhost:5175", "",
    ]), encoding="utf-8")
print("Local authentication configuration ready. Secrets were not printed.")
