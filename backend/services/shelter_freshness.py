"""Age of the shelter record, independent of page polling or retrieval time."""
from datetime import datetime, timedelta, timezone

from backend.config import get_settings


def shelter_freshness(updated_at, *, now=None, stale_after_minutes=None):
    threshold = stale_after_minutes
    if threshold is None:
        threshold = getattr(get_settings(), "shelter_stale_after_minutes", 30)
    checked = now or datetime.now(timezone.utc)
    checked = checked.replace(tzinfo=timezone.utc) if checked.tzinfo is None else checked.astimezone(timezone.utc)
    try:
        value = datetime.fromisoformat(updated_at.replace("Z", "+00:00")) if isinstance(updated_at, str) else updated_at
        if not isinstance(value, datetime):
            raise ValueError("Missing record update time")
        value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
        age = checked - value
        if age < -timedelta(minutes=5):
            raise ValueError("Record update time is in the future")
    except (TypeError, ValueError):
        return {"freshness_status": "unknown", "freshness_note": "Record update time is unknown. Contact the shelter before travelling.",
                "stale_after_minutes": threshold}
    stale = age >= timedelta(minutes=threshold)
    return {"freshness_status": "stale" if stale else "recent",
            "freshness_note": (f"Record is at least {threshold} minutes old. Contact the shelter to confirm availability."
                               if stale else "Recently updated record. Availability can change; contact the shelter before travelling."),
            "stale_after_minutes": threshold}


def capacity_freshness(shelter, *, now=None):
    confirmed = getattr(shelter, "capacity_confirmed_at", None)
    result = shelter_freshness(confirmed, now=now)
    status = result["freshness_status"]
    return {"capacity_confirmed_at": confirmed,
            "capacity_freshness_status": status,
            "capacity_freshness_note": (
                "Capacity confirmation time is unknown. Contact reception before travelling." if status == "unknown" else
                f"Staff capacity confirmation is at least {result['stale_after_minutes']} minutes old. Contact reception before travelling." if status == "stale" else
                "Staff recently confirmed capacity. Reservations and arrivals can change availability.")}
