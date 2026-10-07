"""Verify the running PostgreSQL-backed API; remove only this check's report."""
import uuid

import httpx
from sqlalchemy import text
from backend.database.connection import engine


def main():
    marker = "Local verification " + uuid.uuid4().hex
    headers = {"X-User-Id": "2147483000"}
    try:
        with engine.connect() as connection:
            row = connection.execute(text("SELECT current_database(), inet_server_port(), version()")).one()
            print("Database:", row[0], "port", row[1], row[2].split(" on ")[0])
        with httpx.Client(base_url="http://127.0.0.1:8000", timeout=10) as client:
            assert client.get("/health").json() == {"status": "healthy"}
            assert client.get("/docs").status_code == 200
            assert client.get("/openapi.json").json()["info"]["title"] == "ResQ Kerala API"
            response = client.post("/api/incidents/", headers=headers, json={
                "message": marker, "location": "Local verification", "people_affected": 0,
            })
            assert response.status_code == 201, f"Submission returned HTTP {response.status_code}"
            report = response.json()
            report_id = report["id"]
            assert report["status"] == "SUBMITTED" and report["report_reference"].startswith("RESQ ")
            assert client.get(f"/api/incidents/{report_id}", headers=headers).json()["message"] == marker
            assert any(item["id"] == report_id for item in client.get("/api/incidents/", headers=headers).json())
            assert client.get(f"/api/incidents/{report_id}/history", headers=headers).json()[0]["status"] == "SUBMITTED"
            assert client.get(f"/api/incidents/{report_id}", headers={"X-User-Id": "2147483001"}).status_code == 403
        print("PASS: health, docs, submission, listing, detail, history, and ownership on PostgreSQL.")
    finally:
        with engine.begin() as connection:
            rows = connection.execute(text("SELECT id FROM incident_reports WHERE message = :marker"), {"marker": marker})
            for row in rows:
                connection.execute(text("DELETE FROM status_history WHERE incident_id = :id"), {"id": row[0]})
                connection.execute(text("DELETE FROM incident_reports WHERE id = :id"), {"id": row[0]})
        engine.dispose()
        print("Verification report removed.")


if __name__ == "__main__":
    main()
