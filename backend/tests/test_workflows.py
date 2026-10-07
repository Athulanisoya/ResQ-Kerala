import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    from backend.main import app
    from backend.database.connection import Base, get_db

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)

    def test_db():
        with sessions() as session:
            yield session

    app.dependency_overrides[get_db] = test_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    engine.dispose()


def submit(client):
    return client.post(
        "/api/incidents/",
        headers={"X-User-Id": "1"},
        json={"message": "Local smoke test incident", "location": "Kochi", "people_affected": 2},
    )


def test_submission_details_and_history(client):
    response = submit(client)
    assert response.status_code == 201
    report = response.json()
    assert report["report_reference"].startswith("RESQ ")
    assert report["status"] == "SUBMITTED"
    headers = {"X-User-Id": "1"}
    detail = client.get(f"/api/incidents/{report['id']}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["report_reference"] == report["report_reference"]
    reports = client.get("/api/incidents/", headers=headers)
    assert len(reports.json()) == 1
    history = client.get(f"/api/incidents/{report['id']}/history", headers=headers)
    assert history.status_code == 200
    assert history.json()[0]["status"] == "SUBMITTED"


def test_reports_belong_to_their_user(client):
    report = submit(client).json()
    headers = {"X-User-Id": "2"}
    assert client.get("/api/incidents/", headers=headers).json() == []
    assert client.get(f"/api/incidents/{report['id']}", headers=headers).status_code == 403
    assert client.get(f"/api/incidents/{report['id']}/history", headers=headers).status_code == 403


def test_invalid_request_is_rejected(client):
    assert client.get("/api/incidents/", headers={"X-User-Id": "0"}).status_code == 400
    assert client.get("/api/incidents/").status_code == 422
    assert client.post(
        "/api/incidents/", headers={"X-User-Id": "1"},
        json={"message": "Bad", "location": "Kochi"},
    ).status_code == 422
