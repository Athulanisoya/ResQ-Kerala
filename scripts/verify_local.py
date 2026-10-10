"""Read-only readiness check for the running Week 1 application."""
import httpx
from sqlalchemy import text

from backend.database.connection import engine


def main():
    try:
        with engine.connect() as connection:
            database, port = connection.execute(text("SELECT current_database(), inet_server_port()")).one()
            assert database == "resq_week1" and port == 5443
        with httpx.Client(base_url="http://127.0.0.1:8013", timeout=10, follow_redirects=True) as client:
            health = client.get("/health")
            assert health.status_code == 200 and health.json()["database"] == "connected"
            assert client.get("/").status_code == 200
            assert client.get("/docs").status_code == 200
            assert client.get("/openapi.json").status_code == 200
            assert client.get("/api/incidents/").status_code == 401
        print("PASS: workspace PostgreSQL, health, HTMX home, API docs, and authenticated report gate.")
        print("Use pytest and the documented browser demonstration to verify the reporting workflow.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
