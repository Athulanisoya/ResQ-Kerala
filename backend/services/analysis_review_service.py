"""Evidence views and explicit, revision-bound administrative review notes.

These notes do not mutate the citizen report or operational assessment. A saved
review remains attached to its original analysis revision when new drafts run.
"""
from urllib.parse import urlparse

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend.models import Incident, User
from backend.models.week4_analysis import Week4AnalysisRevision, Week4SuggestionReview


def _safe_url(value):
    if isinstance(value, str) and urlparse(value).scheme in {"https", "http"} and urlparse(value).netloc:
        return value
    return None


def _text(value):
    return str(value).strip() if value is not None else ""


def _review_dict(row, names):
    return {"id": row.id, "suggestion_key": row.suggestion_key, "previous_review_id": row.previous_review_id, "decision": row.decision,
            "original_value": row.original_value, "reviewed_value": row.reviewed_value,
            "note": row.note, "reviewed_by": row.reviewed_by,
            "reviewer_name": names.get(row.reviewed_by, "Unavailable account"), "created_at": row.created_at}


def review_entries(db, revision_id):
    rows = list(db.scalars(select(Week4SuggestionReview).where(
        Week4SuggestionReview.revision_id == revision_id).order_by(Week4SuggestionReview.id.desc())))
    reviewer_ids = {row.reviewed_by for row in rows}
    names = {row.id: row.full_name for row in db.scalars(select(User).where(User.id.in_(reviewer_ids)))} if reviewer_ids else {}
    return [_review_dict(row, names) for row in rows]


def evidence_for(incident, revision):
    result = revision.result if revision else {}
    tools = result.get("results") or {}
    facts = result.get("reported_facts") or {
        "message": result.get("original_text", incident.message), "location": incident.location,
        "people_affected": incident.people_affected, "help_required": incident.help_required,
    }
    location = tools.get("tool_1_extract_location") or {}
    alerts = tools.get("tool_2_check_alerts") or {}
    safety = tools.get("tool_5_retrieve_safety_evidence") or {}
    shelters = tools.get("tool_6_search_shelters") or {}
    passages = [{**p, "source_url": _safe_url(p.get("source_url"))} for p in safety.get("passages", []) if isinstance(p, dict)]
    return {"facts": facts, "location": location, "alerts": alerts,
            "passages": passages, "safety_reason": safety.get("reason") or safety.get("review_notice"),
            "shelters": shelters.get("shelters", []), "shelter_reason": shelters.get("reason"),
            "shelter_query": shelters.get("query"), "model": result.get("model")}


def suggestions_for(incident, revision):
    evidence = evidence_for(incident, revision)
    result = revision.result
    tools = result.get("results") or {}
    facts = evidence["facts"]
    place = evidence["location"].get("place")
    location_value = None
    if evidence["location"].get("status") == "RESOLVED" and isinstance(place, dict) and place.get("name"):
        location_value = place["name"]
        if place.get("district") and place["district"] != place["name"]:
            location_value += ", " + place["district"]
    summary_tool = tools.get("tool_4_create_summary") or {}
    severity_tool = tools.get("tool_3_predict_severity") or {}
    severity = severity_tool.get("predicted_severity")
    severity_value = {"High": "HIGH", "Moderate": "MEDIUM", "Medium": "MEDIUM", "Low": "LOW"}.get(severity, severity)
    alert_value = evidence["alerts"].get("status")
    if alert_value not in {"MATCH", "NO_MATCH", "UNCERTAIN"}:
        alert_value = None
    # Unavailable tools have no suggestion to accept. Uncertainty remains visible
    # in the evidence section rather than becoming a verified value.
    entries = [
        ("translation", "Provisional English translation", result.get("translation"), "original-message", "Model draft; compare every statement with the original text."),
        ("location", "Extracted location", location_value, "location-evidence", evidence["location"].get("reason")),
        ("people_affected", "People affected", facts.get("people_affected"), "reported-people", "Copied from the citizen's reported count; it has not been independently verified."),
        ("help_required", "Requested help", facts.get("help_required"), "reported-help", "Copied from the citizen's requested help."),
        ("summary", "Provisional summary", result.get("generative_summary") or summary_tool.get("summary"), "original-message", "Review against the original report and reported facts."),
        ("severity", "Suggested severity", severity_value, "original-message", severity_tool.get("reason") or "Classifier suggestion. Record an operational assessment separately in Reviewed assessment."),
        ("alert_match", "Alert match", alert_value, "alert-evidence", evidence["alerts"].get("reason")),
    ]
    if evidence["passages"]:
        entries.append(("safety_guidance", "Safety reference excerpts", "\n\n".join(_text(p.get("text")) for p in evidence["passages"]),
                        "safety-evidence", "Reference excerpts retain their source and owner-review status below."))
    if evidence["shelters"]:
        entries.append(("shelter_options", "Shelter options", "\n".join(
            f"{s.get('name', 'Unnamed shelter')}: {s.get('available_capacity', 'unknown')} recorded places; updated {s.get('updated_at') or 'unknown'}"
            for s in evidence["shelters"]), "shelter-evidence", "This is the saved analysis snapshot. Confirm current capacity directly before travelling."))
    return [{"key": key, "label": label, "value": value, "evidence_anchor": "review-" + anchor, "reason": reason,
             "model_version": severity_tool.get("model_version") if key == "severity" else None,
             "generated_at": severity_tool.get("generated_at") if key == "severity" else None}
            for key, label, value, anchor, reason in entries if value is not None and _text(value)]


def context_for(db, incident):
    reporter = db.get(User, incident.user_id)
    account = None if reporter is None else {
        "id": reporter.id, "full_name": reporter.full_name, "email": reporter.email,
        "role": reporter.role.value, "active": reporter.active, "team_id": reporter.team_id,
        "created_at": reporter.created_at,
    }
    revisions = list(db.scalars(select(Week4AnalysisRevision).where(
        Week4AnalysisRevision.incident_id == incident.id).order_by(Week4AnalysisRevision.revision.desc())))
    latest = revisions[0] if revisions else None
    evidence = evidence_for(incident, latest)
    suggestions = suggestions_for(incident, latest) if latest else []
    latest_reviews = review_entries(db, latest.id) if latest else []
    for suggestion in suggestions:
        history = [item for item in latest_reviews if item["suggestion_key"] == suggestion["key"]]
        suggestion["review_history"] = history
        suggestion["review"] = history[0] if history else None
    return {"report": {"id": incident.id, "reference": incident.report_reference, "created_at": incident.created_at,
                       "status": incident.status, "user_id": incident.user_id, **evidence["facts"]},
            "reporter": account, "evidence": evidence, "suggestions": suggestions,
            "revisions": [{"revision": row.revision, "created_at": row.created_at, "created_by": row.created_by,
                           "result": row.result, "reviews": review_entries(db, row.id)} for row in revisions]}


def save_review(db, incident, revision_number, request, reviewer_id):
    # Use the same lock order as analysis creation. A new revision cannot be
    # inserted between checking freshness and saving a review of the old one.
    db.scalar(select(Incident.id).where(Incident.id == incident.id).with_for_update())
    revision = db.scalar(select(Week4AnalysisRevision).where(
        Week4AnalysisRevision.incident_id == incident.id,
        Week4AnalysisRevision.revision == revision_number).with_for_update())
    if revision is None:
        raise HTTPException(status_code=404, detail="Analysis revision not found for this report.")
    newest = db.scalar(select(Week4AnalysisRevision.revision).where(
        Week4AnalysisRevision.incident_id == incident.id).order_by(Week4AnalysisRevision.revision.desc()).limit(1))
    if newest != revision_number:
        raise HTTPException(status_code=409, detail="A newer analysis revision is available. Review its evidence before deciding.")
    suggestion = next((s for s in suggestions_for(incident, revision) if s["key"] == request.suggestion_key), None)
    if suggestion is None:
        raise HTTPException(status_code=422, detail="This revision has no available suggestion for that field.")
    previous_id = db.scalar(select(Week4SuggestionReview.id).where(
        Week4SuggestionReview.revision_id == revision.id,
        Week4SuggestionReview.suggestion_key == request.suggestion_key).order_by(Week4SuggestionReview.id.desc()).limit(1)) or 0
    if previous_id != request.expected_review_id:
        raise HTTPException(status_code=409, detail="This suggestion was reviewed in another tab. Reload the latest decision before saving.")
    value = suggestion["value"] if request.decision == "accepted" else None
    if request.decision == "edited":
        value = (request.value or "").strip()
        if not value:
            raise HTTPException(status_code=422, detail="Enter a reviewed value before saving an edit.")
        if request.suggestion_key == "people_affected":
            try:
                value = int(value)
            except ValueError:
                raise HTTPException(status_code=422, detail="People affected must be a whole number.") from None
            if not 0 <= value <= 100000:
                raise HTTPException(status_code=422, detail="People affected must be between 0 and 100000.")
        if request.suggestion_key == "severity" and value not in {"LOW", "MEDIUM", "HIGH", "UNKNOWN"}:
            raise HTTPException(status_code=422, detail="Severity must be LOW, MEDIUM, HIGH or UNKNOWN.")
        if request.suggestion_key == "alert_match" and value not in {"MATCH", "NO_MATCH", "UNCERTAIN"}:
            raise HTTPException(status_code=422, detail="Alert match must be MATCH, NO_MATCH or UNCERTAIN.")
        if request.suggestion_key in {"location", "help_required"} and len(value) > 255:
            raise HTTPException(status_code=422, detail="Location and help values must be at most 255 characters.")
    if request.decision == "rejected" and not request.note:
        raise HTTPException(status_code=422, detail="Give a reason for rejecting this suggestion.")
    row = Week4SuggestionReview(revision_id=revision.id, suggestion_key=request.suggestion_key,
                               previous_review_id=previous_id,
                               decision=request.decision, original_value=suggestion["value"], reviewed_value=value,
                               note=request.note or None, reviewed_by=reviewer_id)
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="This suggestion was reviewed in another tab. Reload the latest decision before saving.") from None
    db.refresh(row)
    reviewer = db.get(User, reviewer_id)
    return _review_dict(row, {reviewer_id: reviewer.full_name if reviewer else "Unavailable account"})
