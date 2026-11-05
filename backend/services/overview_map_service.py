"""Current admin-issued alert coverage and recorded shelters for the Overview map.

District colour is a summary of the highest active alert anywhere in a district;
district_level separately states the actual district-wide coverage. Locality
points are sourced place centres, never invented alert-area boundaries.
"""
from datetime import datetime, timezone
from functools import lru_cache
import json
import math
from pathlib import Path
import unicodedata

from sqlalchemy import select

from backend.ai.location_extractor import list_places
from backend.models import Role, Team
from backend.models.shelter import Shelter
from backend.services.alert_service import list_alerts, utc
from backend.services.shelter_freshness import shelter_freshness


MAP_DATA = Path(__file__).resolve().parents[2] / "data" / "map"
RANK = {"GREEN": 0, "YELLOW": 1, "ORANGE": 2, "RED": 3}
ALERT_FIELDS = (
    "id", "title", "message", "level", "place_id", "place_name", "place_kind",
    "district_id", "district", "starts_at", "expires_at", "updated_at",
)


def highest(alerts):
    return max((alert["level"] for alert in alerts), key=RANK.__getitem__, default="GREEN")


@lru_cache(maxsize=1)
def district_boundaries():
    return json.loads((MAP_DATA / "kerala-districts.geojson").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def locality_coordinates():
    return {item["id"]: item for item in json.loads(
        (MAP_DATA / "locality-points.json").read_text(encoding="utf-8")
    )["places"]}


def valid_coordinates(latitude, longitude):
    return (isinstance(latitude, (int, float)) and not isinstance(latitude, bool)
            and isinstance(longitude, (int, float)) and not isinstance(longitude, bool)
            and math.isfinite(latitude) and math.isfinite(longitude)
            and -90 <= latitude <= 90 and -180 <= longitude <= 180)


def district_key(value):
    """Normalize exact district names without interpreting locality or address text."""
    return " ".join(unicodedata.normalize("NFC", value or "").translate({
        0x200B: None, 0x200C: None, 0x200D: None, 0xFEFF: None,
    }).casefold().split())


def map_payload(db, user, *, now=None):
    checked = utc(now or datetime.now(timezone.utc))
    active = [{key: getattr(alert, key) for key in ALERT_FIELDS}
              for alert in list_alerts(db, now=checked)]
    places = list_places()
    points = locality_coordinates()
    district_aliases = {}
    for place in (place for place in places if place.kind == "district"):
        for name in (place.name, *place.aliases):
            district_aliases.setdefault(district_key(name), set()).add(place.id)
    districts = []
    for place in (place for place in places if place.kind == "district"):
        alerts = [alert for alert in active if alert["district_id"] == place.id]
        whole = [alert for alert in alerts if alert["place_kind"] == "district"]
        local = [alert for alert in alerts if alert["place_kind"] == "locality"]
        level = highest(alerts)
        districts.append({
            "id": place.id, "name": place.name, "level": level, "worst_level": level,
            "district_level": highest(whole), "coverage": "district" if whole else "locality" if local else "none",
            "active_alert_count": len(alerts), "locality_alert_count": len(local), "alerts": alerts,
        })
    localities = []
    for place in (place for place in places if place.kind == "locality"):
        own = [alert for alert in active if alert["place_id"] == place.id]
        inherited = [alert for alert in active if alert["place_kind"] == "district" and alert["district_id"] == place.district_id]
        point = points.get(place.id, {})
        latitude, longitude = point.get("latitude"), point.get("longitude")
        located = valid_coordinates(latitude, longitude)
        localities.append({
            "id": place.id, "name": place.name, "district_id": place.district_id, "district": place.district,
            "latitude": latitude if located else None, "longitude": longitude if located else None,
            "coordinate_source": point.get("source_url") if located else None,
            "coordinate_status": "located" if located else "unlocated",
            "level": highest(own + inherited), "own_level": highest(own), "inherited_level": highest(inherited),
            "alerts": own + inherited,
        })
    team = db.get(Team, user.team_id) if user.role == Role.RESPONSE_TEAM and user.team_id is not None else None
    shelters = []
    for row in db.scalars(select(Shelter).order_by(Shelter.district, Shelter.name, Shelter.id)):
        located = valid_coordinates(row.latitude, row.longitude)
        matches = district_aliases.get(district_key(row.district), set())
        district_id = next(iter(matches)) if len(matches) == 1 else None
        can_manage = user.role == Role.ADMIN or (team is not None and team.team_type.casefold() == "shelter" and row.team_id == team.id)
        shelters.append({
            "id": row.id, "name": row.name, "district": row.district, "district_id": district_id, "locality": row.locality,
            "address": row.address, "location": row.location, "status": row.status,
            "latitude": row.latitude if located else None, "longitude": row.longitude if located else None,
            "coordinate_status": "located" if located else "unlocated",
            "available_capacity": row.available_capacity, "capacity": row.capacity, "occupied": row.occupied,
            "contact": row.contact, "updated_at": row.updated_at,
            **shelter_freshness(row.updated_at, now=checked),
            "can_register": user.role == Role.CITIZEN and row.status == "OPEN" and row.available_capacity > 0,
            "can_manage_registrations": bool(can_manage), "registration_url": f"/shelters/{row.id}/join",
        })
    unlocated_ids = {place["id"] for place in localities if place["coordinate_status"] == "unlocated"}
    return {
        "generated_at": checked, "refresh_seconds": 30,
        "legend": [{"level": level, "label": label} for level, label in (
            ("RED", "Red alert"), ("ORANGE", "Orange alert"), ("YELLOW", "Yellow alert"),
            ("GREEN", "No active admin alert"),
        )],
        "districts": districts, "localities": localities, "shelters": shelters,
        "unlocated_shelter_count": sum(row["coordinate_status"] == "unlocated" for row in shelters),
        "unlocated_alert_count": sum(alert["place_id"] in unlocated_ids for alert in active),
        "attribution": {
            "boundary": "District boundaries: geoBoundaries / Pathways Data / Local Government Directory (ODbL 1.0; 2021 source).",
            "points": "Place centres: GeoNames (CC BY 4.0); exact-name matches within the recorded district.",
            "source_urls": ["https://www.geoboundaries.org/api/current/gbOpen/IND/ADM2/", "https://www.geonames.org/export/"],
            "limitations": [
                "Green means no active administrator-issued alert in this app, not proof of safety.",
                "District colour summarises the highest alert anywhere in the district; locality alerts do not cover the whole district.",
                "Locality markers show sourced place centres, not official alert-area boundaries. Some catalog places have no verified map point.",
                "Shelter markers use recorded coordinates. Contact the shelter to confirm availability; a map check does not confirm capacity.",
            ],
        },
    }
