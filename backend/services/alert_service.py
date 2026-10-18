"""Alert lifecycle and conservative geographic matching, independent of an LLM."""
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import case, select
from sqlalchemy.orm import Session

from backend.ai.location_extractor import LocationExtraction, get_place
from backend.models.alert import Alert
from backend.schemas.alert_schema import AlertCreate, AlertMatch, AlertResponse, AlertUpdate


def utc(value: datetime) -> datetime:
    # SQLite discards timezone metadata; stored timestamps are always UTC.
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def serialize_alert(alert: Alert, now: datetime | None = None) -> AlertResponse:
    now = utc(now or datetime.now(timezone.utc))
    status = "ACTIVE"
    if alert.expired_at is not None or utc(alert.expires_at) <= now:
        status = "EXPIRED"
    elif utc(alert.starts_at) > now:
        status = "SCHEDULED"
    return AlertResponse(
        **{name: getattr(alert, name) for name in AlertResponse.model_fields if name != "status"},
        status=status,
    )


def list_alerts(db: Session, include_inactive: bool = False, *, now: datetime | None = None) -> list[AlertResponse]:
    now = utc(now or datetime.now(timezone.utc))
    query = select(Alert)
    if not include_inactive:
        query = query.where(Alert.expired_at.is_(None), Alert.starts_at <= now, Alert.expires_at > now)
    severity = case((Alert.level == "RED", 3), (Alert.level == "ORANGE", 2), else_=1)
    query = query.order_by(severity.desc(), Alert.starts_at.desc(), Alert.id.desc())
    return [serialize_alert(alert, now) for alert in db.scalars(query)]


def _coverage(place_id: str) -> dict:
    place = get_place(place_id)
    if place is None:
        raise HTTPException(status_code=422, detail="Choose a known Kerala place from the alert location list.")
    return {
        "place_id": place.id,
        "place_name": place.name,
        "place_kind": place.kind,
        "district_id": place.district_id,
        "district": place.district,
    }


def create_alert(db: Session, data: AlertCreate, created_by_id: int) -> AlertResponse:
    values = data.model_dump()
    coverage = _coverage(values.pop("place_id"))
    alert = Alert(**values, **coverage, created_by_id=created_by_id)
    try:
        db.add(alert)
        db.commit()
        db.refresh(alert)
    except Exception:
        db.rollback()
        raise
    return serialize_alert(alert)


def _locked_alert(db: Session, alert_id: int) -> Alert:
    alert = db.scalar(select(Alert).where(Alert.id == alert_id).with_for_update())
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found.")
    return alert


def update_alert(db: Session, alert_id: int, data: AlertUpdate) -> AlertResponse:
    try:
        alert = _locked_alert(db, alert_id)
        if alert.expired_at is not None:
            raise HTTPException(status_code=409, detail="This alert was explicitly expired. Create a new alert to issue it again.")
        changes = data.model_dump(exclude_unset=True)
        starts_at = utc(changes.get("starts_at", alert.starts_at))
        expires_at = utc(changes.get("expires_at", alert.expires_at))
        if expires_at <= starts_at:
            raise HTTPException(status_code=422, detail="The alert expiry must be after its start.")
        if "place_id" in changes:
            changes.update(_coverage(changes.pop("place_id")))
        for name, value in changes.items():
            setattr(alert, name, value)
        alert.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(alert)
    except Exception:
        db.rollback()
        raise
    return serialize_alert(alert)


def expire_alert(db: Session, alert_id: int) -> AlertResponse:
    try:
        alert = _locked_alert(db, alert_id)
        if alert.expired_at is None:
            alert.expired_at = datetime.now(timezone.utc)
            alert.updated_at = alert.expired_at
            db.commit()
            db.refresh(alert)
    except Exception:
        db.rollback()
        raise
    return serialize_alert(alert)


def match_alerts(db: Session, extraction: LocationExtraction) -> AlertMatch:
    now = datetime.now(timezone.utc)
    if extraction.status != "RESOLVED" or extraction.place is None:
        return AlertMatch(status="UNCERTAIN", reason=extraction.reason, alerts=[], checked_at=now)
    # Revalidate catalog membership so callers cannot fabricate a resolved place.
    place = get_place(extraction.place.id)
    if place is None:
        return AlertMatch(status="UNCERTAIN", reason="The reported place is not in the verified location catalog.", alerts=[], checked_at=now)
    active = list_alerts(db, now=now)
    matches = [alert for alert in active if alert.place_id == place.id or (
        alert.place_kind == "district" and alert.district_id == place.district_id
    )]
    if matches:
        return AlertMatch(status="MATCH", reason=f"An active administrator-issued alert covers {place.name}.", alerts=matches, checked_at=now)
    if place.kind == "district" and any(alert.district_id == place.district_id for alert in active):
        return AlertMatch(
            status="UNCERTAIN", reason=f"Active alerts cover specific localities in {place.name}. Provide the locality to check coverage.",
            alerts=[], checked_at=now,
        )
    return AlertMatch(status="NO_MATCH", reason=f"No active administrator-issued alert covers {place.name} at the time checked.", alerts=[], checked_at=now)
