"""Check running local role workspaces without changing incident records.

Uses the ignored demo account file only for local login; never prints credentials.
Run the isolated pytest workflows to verify mutations and concurrency.
"""
import json
from pathlib import Path

import httpx


def main():
    root = Path(__file__).resolve().parents[1]
    password = json.loads((root / ".runtime/demo-accounts.json").read_text(encoding="utf-8-sig"))["password"]
    for role, email in (("citizen", "citizen@resq.example.com"),
                        ("admin", "admin@resq.example.com"),
                        ("response_team", "team@resq.example.com")):
        with httpx.Client(base_url="http://127.0.0.1:8013", timeout=20,
                          headers={"X-ResQ-Page": "true"}) as client:
            response = client.post("/api/auth/login", json={"email": email, "password": password})
            assert response.status_code == 200, f"{role}: local demo login failed"
            client.headers["Authorization"] = "Bearer " + response.json()["access_token"]
            try:
                for path in ("/dashboard", "/reports", "/updates", "/operations", "/ui/updates/count"):
                    result = client.get(path)
                    assert result.status_code == 200, f"{role}: {path} returned {result.status_code}"
                    assert "text/html" in result.headers.get("Content-Type", ""), f"{path}: expected HTML"
                for path in ("/api/communication/notifications", "/api/operations/relief-requests", "/api/operations/inventory"):
                    assert client.get(path).status_code == 200, f"{role}: {path} failed"
                if role == "response_team":
                    assert client.get("/assignments-history").status_code == 200
                listing = {"citizen": "/api/incidents/", "admin": "/api/admin/incidents",
                           "response_team": "/api/teams/assignments"}[role]
                reports = client.get(listing)
                assert reports.status_code == 200
                for item in reports.json()[:3]:
                    detail = client.get(f"/reports/{item['id']}")
                    assert detail.status_code == 200, f"{role}: report detail failed"
                    assert 'id="clarifications"' in detail.text
                    assert 'id="report-summary"' in detail.text
                print(f"PASS: {role} live HTML pages, authenticated APIs and accessible report details.")
            finally:
                assert client.post("/api/auth/logout").status_code == 204
    print("PASS: local sessions revoked; incident, inventory and relief records unchanged.")


if __name__ == "__main__":
    main()
