"""Run inside the app container to check HTTP, PostgreSQL and Ollama tools."""
import asyncio
import json
from urllib.request import urlopen

from backend.ai.ollama_status import get_ollama_status
from backend.config import get_settings


def verify():
    with urlopen("http://127.0.0.1:8013/health", timeout=5) as response:
        health = json.load(response)
    if not isinstance(health, dict) or health.get("status") != "ok" or health.get("database") != "connected":
        raise SystemExit("Application/database health check failed.")
    with urlopen("http://127.0.0.1:8013/", timeout=5) as response:
        if b"htmx" not in response.read().lower():
            raise SystemExit("The HTMX frontend check failed.")
    status = asyncio.run(get_ollama_status(get_settings()))
    if not status["configured"]:
        raise SystemExit(status["reason"])
    print(f"Ready: HTMX frontend, PostgreSQL, Ollama and tool-capable model {status['model']}.")


def main():
    try:
        verify()
    except (OSError, ValueError):
        # Never echo configuration validation inputs or private connection URLs.
        raise SystemExit("Docker verification failed. Check service health, configuration and logs.") from None


if __name__ == "__main__":
    main()
