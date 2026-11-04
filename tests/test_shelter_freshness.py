"""A fresh page check cannot make an old shelter record look current."""
from contextlib import closing
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import update

from backend.database.connection import get_db
from backend.main import app as api
from backend.models.shelter import Shelter
from backend.services.shelter_freshness import shelter_freshness
from tests.test_web import clients, login


@pytest.mark.parametrize("age,status", [(0, "recent"), (29, "recent"), (30, "stale"), (300, "stale")])
def test_record_age_boundary_is_independent_of_check_time(age, status):
    now = datetime(2026, 11, 4, 12, tzinfo=timezone.utc)
    result = shelter_freshness(now - timedelta(minutes=age), now=now, stale_after_minutes=30)
    assert result["freshness_status"] == status and result["stale_after_minutes"] == 30


@pytest.mark.parametrize("value", [None, "invalid", "2050-01-01T12:00:00Z"])
def test_missing_invalid_and_future_times_are_explicitly_unknown(value):
    assert shelter_freshness(value, now=datetime(2026, 11, 4, tzinfo=timezone.utc))["freshness_status"] == "unknown"


def test_legacy_naive_utc_and_configurable_threshold():
    now = datetime(2026, 11, 4, 12, tzinfo=timezone.utc)
    assert shelter_freshness(datetime(2026, 11, 4, 11, 45), now=now, stale_after_minutes=10)["freshness_status"] == "stale"
    assert shelter_freshness("2026-11-04T11:45:00Z", now=now, stale_after_minutes=60)["freshness_status"] == "recent"


@pytest.mark.parametrize("status,minutes", [("recent", 1), ("stale", 90), ("unknown", None)])
def test_page_and_poll_show_record_time_state_and_missing_contact(clients, status, minutes):
    citizen, admin, _ = clients
    login(admin, "admin"); login(citizen, "citizen")
    created = admin.post("/api/shelters", json={"name": "Timestamp test shelter", "location": "Kochi School",
                                               "capacity": 20, "occupied": 2}).json()
    value = datetime.now(timezone.utc) - timedelta(minutes=minutes) if minutes is not None else None
    with closing(api.dependency_overrides[get_db]()) as sessions:
        db = next(sessions)
        db.execute(update(Shelter).where(Shelter.id == created["id"]).values(updated_at=value))
        db.commit()
    original = citizen.get(f"/api/shelters/{created['id']}").json()
    assert original["freshness_status"] == status
    page = citizen.get("/shelters?q=Timestamp", headers={"HX-Request": "true"})
    assert f'data-freshness="{status}"' in page.text
    assert "Last record update:" in page.text and "Not provided — contact the local response office" in page.text
    assert "Page checks do not confirm" in page.text
    live = citizen.get("/ui/shelters/live?q=Timestamp", headers={"HX-Request": "true"})
    assert f'data-freshness="{status}"' in live.text and "Page checked" in live.text
    assert "Stale record" in live.text if status == "stale" else "Update time unknown" in live.text if status == "unknown" else "Recently updated record" in live.text
    after = citizen.get(f"/api/shelters/{created['id']}").json()
    assert after["updated_at"] == original["updated_at"]
