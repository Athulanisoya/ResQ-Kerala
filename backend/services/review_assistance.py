"""Bounded, source-linked missing-fact questions; no question is sent automatically."""
import hashlib
import json
from sqlalchemy import select
from backend.ai.location_extractor import extract_location, get_place, list_places
from backend.models.review_assistance import LocationConfirmation
from backend.schemas.location_schema import LocationExtraction
from backend.schemas.location_analysis_schema import LocationAnalysisResult
from backend.services.alert_service import match_alerts


def report_input_hash(incident):
    return hashlib.sha256(json.dumps([incident.message, incident.location, incident.people_affected,
                                     incident.help_required], ensure_ascii=False).encode()).hexdigest()


def latest_confirmation(db, incident):
    return db.scalar(select(LocationConfirmation).where(
        LocationConfirmation.incident_id == incident.id,
        LocationConfirmation.input_hash == report_input_hash(incident)
    ).order_by(LocationConfirmation.id.desc()).limit(1))


def confirmed_extraction(db, incident):
    row = latest_confirmation(db, incident)
    place = get_place(row.place_id) if row else None
    if not place:
        return None
    precision = "The district is confirmed; the supplied locality is not independently verified." if place.kind == "district" else "The selected locality is confirmed by a person, not independently verified in the field."
    return LocationExtraction(status="RESOLVED", place=place, candidates=[place],
                              matched_text=[row.locality or place.name],
                              reason=f"Explicit human confirmation #{row.id}. {precision}")


def confirmed_analysis(db, incident):
    extraction = confirmed_extraction(db, incident)
    if extraction is None:
        return None
    return LocationAnalysisResult(extraction=extraction, alert_match=match_alerts(db, extraction), mode="deterministic")


def location_follow_up(db, incident):
    original = extract_location(incident.message, incident.location)
    confirmation = latest_confirmation(db, incident)
    extraction = confirmed_extraction(db, incident) or original
    district_only = original.place is not None and original.place.kind == "district"
    uncertain = original.status == "UNCERTAIN" or district_only
    question = "Which district is this locality in?" if not original.candidates or len({p.district_id for p in original.candidates}) > 1 else "Which of these places is the incident in? Please confirm the locality and district."
    if district_only:
        question = f"Which locality or nearby landmark in {original.place.district} is affected?"
    return {
        "input_hash": report_input_hash(incident), "requires_clarification": uncertain and confirmation is None,
        "question": question, "extraction": extraction.model_dump(mode="json"),
        "candidates": [p.model_dump(mode="json") for p in original.candidates],
        "districts": [p.model_dump(mode="json") for p in list_places() if p.kind == "district"],
        "confirmation": ({"id": confirmation.id, "place_id": confirmation.place_id,
            "locality": confirmation.locality, "confirmed_by": confirmation.confirmed_by,
            "created_at": confirmation.created_at, "note": confirmation.note,
            "precision": get_place(confirmation.place_id).kind} if confirmation else None),
    }


def clarification_suggestions(db, incident):
    if incident.status in {"CLOSED", "CANCELLED", "REJECTED"}:
        return []
    suggestions = []
    follow_up = location_follow_up(db, incident)
    if follow_up["requires_clarification"]:
        suggestions.append({"field": "location", "question": follow_up["question"],
            "reason": follow_up["extraction"]["reason"], "evidence": incident.location, "anchor": "report-location"})
    if incident.people_affected is None or incident.people_affected <= 0:
        suggestions.append({"field": "people", "question": "How many people need help, including anyone who needs assistance moving?",
            "reason": "The report does not specify a positive number of people affected.",
            "evidence": str(incident.people_affected) if incident.people_affected is not None else "Not specified", "anchor": "report-people"})
    help_text = (incident.help_required or "").strip()
    if not help_text or help_text.casefold() in {"help", "other", "unknown", "not sure", "സഹായം"}:
        suggestions.append({"field": "help", "question": "What help is needed now: evacuation, medical assistance, food, drinking water, or another need?",
            "reason": "The type of help is missing or too general.", "evidence": help_text or "Not specified", "anchor": "report-help"})
    return suggestions
