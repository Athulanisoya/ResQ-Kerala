"""Offline retries retain one report and one set of review/notification records."""
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from .test_auth import api, synthetic_password_hash
from backend.models import Incident, IncidentStatusHistory, Role, User
from backend.models.communication import Notification
from backend.models.incident_summary import IncidentSummary
from backend.models.location_analysis import LocationAnalysis
from backend.models.report_analysis import ReportAnalysis


def submit(api, **changes):
    return api.client.post("/api/incidents/", headers=api.headers("citizen"), json={
        "message": "Synthetic offline test: flooding in our street.", "location": "Aluva",
        "people_affected": 3, "help_required": "Rescue", **changes,
    })


def counts(db):
    return tuple(db.scalar(select(func.count()).select_from(model)) for model in
                 (Incident, IncidentStatusHistory, ReportAnalysis, IncidentSummary, LocationAnalysis, Notification))


def test_identical_retry_returns_original_report_without_side_effects(api):
    key = str(uuid4())
    first = submit(api, client_submission_id=key)
    assert first.status_code == 201, first.text
    assert first.json()["client_submission_id"] == key
    with api.sessions() as db:
        before = counts(db)
    # Defaults/whitespace are normalized by the same public request schema.
    retried = submit(api, client_submission_id=key.upper(), message="  Synthetic offline test: flooding in our street.  ",
                     disaster_type="Flood")
    assert retried.status_code == 201 and retried.json() == first.json()
    with api.sessions() as db:
        assert counts(db) == before
        assert before == (1, 1, 1, 1, 1, 2)


@pytest.mark.parametrize("change", [
    {"message": "Different flooding report in the same area"}, {"location": "Kochi"},
    {"people_affected": 4}, {"help_required": "Food"}, {"disaster_type": "Landslide"},
])
def test_reusing_key_with_changed_payload_conflicts_without_overwrite(api, change):
    key = str(uuid4())
    first = submit(api, client_submission_id=key)
    with api.sessions() as db:
        before = counts(db)
    response = submit(api, client_submission_id=key, **change)
    assert response.status_code == 409, response.text
    assert "different details" in response.json()["detail"]
    original = api.client.get(f"/api/incidents/{first.json()['id']}", headers=api.headers("citizen"))
    assert original.json() == first.json()
    with api.sessions() as db:
        assert counts(db) == before


def test_same_client_key_is_private_and_scoped_per_citizen(api, synthetic_password_hash):
    key = str(uuid4())
    first = submit(api, client_submission_id=key)
    with api.sessions() as db:
        other = User(full_name="Other Synthetic Citizen", email="other-offline@example.com", role=Role.CITIZEN,
                     password_hash=synthetic_password_hash)
        db.add(other)
        db.commit()
    from .test_auth import TEST_PASSWORD
    token = api.client.post("/api/auth/login", json={"email": "other-offline@example.com", "password": TEST_PASSWORD}).json()["access_token"]
    second = api.client.post("/api/incidents/", headers={"Authorization": "Bearer " + token}, json={
        "message": "A different private citizen report.", "location": "Kochi", "client_submission_id": key,
    })
    assert second.status_code == 201 and second.json()["id"] != first.json()["id"]
    assert second.json()["user_id"] != first.json()["user_id"]


def test_calls_without_client_key_keep_existing_create_behavior(api):
    first, second = submit(api), submit(api)
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] != second.json()["id"]
    assert first.json()["client_submission_id"] is None


@pytest.mark.parametrize("key", ["", "not-a-uuid", 123, "x" * 10000], ids=["empty", "invalid", "numeric", "too-long"])
def test_invalid_client_key_creates_nothing(api, key):
    assert submit(api, client_submission_id=key).status_code == 422
    with api.sessions() as db:
        assert counts(db) == (0, 0, 0, 0, 0, 0)


def test_retry_after_administrator_review_preserves_review_and_original_fingerprint(api):
    key = str(uuid4())
    first = submit(api, client_submission_id=key).json()
    reviewed = api.client.patch(f"/api/incidents/{first['id']}/status", headers=api.headers("admin"),
                               json={"status": "VERIFIED", "note": "Synthetic review completed"})
    assert reviewed.status_code == 200
    with api.sessions() as db:
        before = counts(db)
    retry = submit(api, client_submission_id=key)
    assert retry.status_code == 201 and retry.json()["status"] == "VERIFIED"
    with api.sessions() as db:
        assert counts(db) == before
