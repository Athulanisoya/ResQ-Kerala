"""Create independent private Docker credentials without changing host setup."""
import argparse
import os
from pathlib import Path
import secrets


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = "gemma4:e4b-it-q4_K_M"


def configure(destination: Path, *, port: int = 8013) -> bool:
    """Exclusive creation preserves existing credentials and database volumes."""
    if not 1 <= port <= 65535:
        raise ValueError("The web port must be between 1 and 65535.")
    content = (
        "# Private Docker configuration. Keep this file outside Git and images.\n"
        "# Always pass --env-file .env.docker to Docker Compose.\n"
        f"POSTGRES_PASSWORD={secrets.token_hex(32)}\n"
        f"JWT_SECRET={secrets.token_hex(48)}\n"
        f"WEB_PORT={port}\n"
        f"OLLAMA_MODEL={DEFAULT_MODEL}\n"
        "SHELTER_STALE_AFTER_MINUTES=30\n"
    )
    try:
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return False
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8013, help="Host web port; use 8014 beside a host app on 8013")
    args = parser.parse_args(argv)
    try:
        created = configure(ROOT / ".env.docker", port=args.port)
    except (OSError, ValueError):
        parser.exit(1, "Docker configuration could not be created. Check the port and project directory permissions.\n")
    print("Created private .env.docker." if created else "Kept existing .env.docker unchanged (including its web port).")
    print("Start: docker compose --env-file .env.docker up -d --build")


if __name__ == "__main__":
    main()
