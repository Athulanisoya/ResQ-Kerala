"""Explainable candidate ranking; assignment remains an explicit admin action."""
from datetime import datetime, timezone
import json

from fastapi import HTTPException
from sqlalchemy import func, select

from backend.ai.location_extractor import extract_location, get_place, list_places
from backend.models import Incident, Role, Team, User
from backend.models.admin_audit import AdminChange
from backend.models.team_coverage import TeamOperationalProfile
from backend.services.review_assistance import confirmed_extraction


CAPABILITIES = {
    "water_rescue": "Water rescue", "evacuation": "Evacuation", "medical_support": "Medical support",
    "food_distribution": "Food and supply distribution", "shelter_support": "Shelter support",
    "field_assessment": "Field assessment",
}
TEAM_TYPES = ("Rescue", "Relief", "Shelter", "Investigation")


def require_team(db, team_id, *, lock=False):
    query = select(Team).where(Team.id == team_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    team = db.scalar(query)
    if team is None:
        raise HTTPException(404, "Response team not found")
    return team


def _profile_values(profile):
    return {"area_ids": list(profile.area_ids), "capabilities": list(profile.capabilities),
            "note": profile.note, "version": profile.version} if profile else {
                "area_ids": [], "capabilities": [], "note": "", "version": 0}


def coverage_payload(db, team_id):
    team = require_team(db, team_id)
    profile = db.get(TeamOperationalProfile, team_id)
    values = _profile_values(profile)
    return {"team": {"id": team.id, "name": team.name, "team_type": team.team_type, "status": team.status},
            **values, "configured": profile is not None,
            "areas": [place.model_dump(mode="json") for key in values["area_ids"] if (place := get_place(key))],
            "updated_at": profile.updated_at if profile else None,
            "updated_by_id": profile.updated_by_id if profile else None}


def update_coverage(db, team_id, actor, data):
    require_team(db, team_id, lock=True)
    profile = db.scalar(select(TeamOperationalProfile).where(TeamOperationalProfile.team_id == team_id)
                        .with_for_update().execution_options(populate_existing=True))
    before = _profile_values(profile)
    if data.expected_version != before["version"]:
        raise HTTPException(409, "Team coverage changed. Reload the latest version before saving.")
    area_ids = sorted(set(data.area_ids))
    if any(get_place(key) is None for key in area_ids):
        raise HTTPException(422, "Choose operating areas from the Kerala place catalog.")
    if profile is None:
        profile = TeamOperationalProfile(team_id=team_id, version=1, updated_by_id=actor.id)
        db.add(profile)
    else:
        profile.version += 1
    profile.area_ids = area_ids
    profile.capabilities = sorted(set(data.capabilities))
    profile.note = data.note
    profile.updated_by_id = actor.id
    profile.updated_at = datetime.now(timezone.utc)
    db.add(AdminChange(actor_id=actor.id, target_kind="team", target_id=team_id, action="operating_coverage",
                       details=json.dumps({"before": before, "after": _profile_values(profile)}, sort_keys=True)))
    db.commit()
    return coverage_payload(db, team_id)


def area_match(place, profile):
    """Return a bounded, explained match without guessing missing locations."""
    areas = [area for key in (profile.area_ids if profile else []) if (area := get_place(key))]
    if place is None:
        return 0, "unknown_location", "Incident location is uncertain; an operating-area match cannot be established."
    if not areas:
        return 0, "unknown_coverage", "Operating areas are not configured; confirm that this team can cover the incident location."
    if place.kind == "locality" and any(area.id == place.id for area in areas):
        return 40, "locality", f"Declared operating area includes {place.name} locality."
    if any(area.kind == "district" and area.id == place.district_id for area in areas):
        return 20, "district", f"Declared operating area includes {place.district} district."
    if place.kind == "district" and any(area.district_id == place.id for area in areas):
        return 10, "partial_district", "The team covers localities in this district; clarify the incident locality before assigning."
    return -1, "outside_coverage", "The resolved incident location is outside this team's declared operating areas."


def recommendations(db, incident_id, *, team_type="Rescue", capability=None):
    incident = db.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(404, "Incident not found")
    extraction = confirmed_extraction(db, incident)
    source = "human_confirmation" if extraction else "catalog_extraction"
    extraction = extraction or extract_location(incident.message, incident.location)
    place = extraction.place if extraction.status == "RESOLVED" else None
    teams = list(db.scalars(select(Team).order_by(Team.name, Team.id)))
    profiles = {row.team_id: row for row in db.scalars(select(TeamOperationalProfile))}
    members = dict(db.execute(select(User.team_id, func.count(User.id)).where(
        User.role == Role.RESPONSE_TEAM, User.active.is_(True), User.team_id.is_not(None)).group_by(User.team_id)).all())
    excluded = {"different_type": 0, "unavailable": 0, "no_active_account": 0, "missing_capability": 0, "outside_coverage": 0}
    candidates = []
    for team in teams:
        if team.team_type.casefold() != team_type.casefold():
            excluded["different_type"] += 1
            continue
        if team.status != "AVAILABLE":
            excluded["unavailable"] += 1
            continue
        if not members.get(team.id):
            excluded["no_active_account"] += 1
            continue
        profile = profiles.get(team.id)
        if capability and capability not in (profile.capabilities if profile else []):
            excluded["missing_capability"] += 1
            continue
        score, match, reason = area_match(place, profile)
        if match == "outside_coverage":
            excluded[match] += 1
            continue
        reasons = [f"Available {team_type.lower()} team with {members[team.id]} active team account(s).", reason]
        if capability:
            score += 20
            reasons.append("Administrator-declared capability: " + CAPABILITIES[capability] + ".")
        candidates.append({"team_id": team.id, "name": team.name, "team_type": team.team_type,
                           "status": team.status, "score": score, "area_match": match, "reasons": reasons,
                           "capabilities": list(profile.capabilities) if profile else [],
                           "coverage_version": profile.version if profile else 0})
    candidates.sort(key=lambda item: (-item["score"], item["name"].casefold(), item["team_id"]))
    can_assign = incident.status == "VERIFIED" and incident.assigned_team_id is None
    return {"incident_id": incident.id, "team_type": team_type, "required_capability": capability,
            "generated_at": datetime.now(timezone.utc), "can_assign": can_assign,
            "assignment_notice": "Review a suggested team and explicitly assign it. Availability is checked again when assigning." if can_assign
                else "Recommendations are a preview. Only a verified, unassigned report can be assigned.",
            "location": extraction.model_dump(mode="json"), "location_source": source,
            "teams": candidates, "excluded_counts": excluded,
            "ranking_note": "Ordering uses declared area coverage and the selected capability; it is not a probability, travel time or assessment of field readiness."}


def coverage_catalog():
    return {"areas": [place.model_dump(mode="json") for place in list_places()],
            "capabilities": [{"id": key, "label": label} for key, label in CAPABILITIES.items()],
            "team_types": list(TEAM_TYPES)}
