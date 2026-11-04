"""Explainable multilingual event-concept matching over a bounded time window.

This small English/Malayalam concept vocabulary is an offline semantic aid,
not a general embedding model or an identity match between affected people.
"""
from datetime import datetime, timezone
from difflib import SequenceMatcher
import hashlib
import json
import re
import unicodedata
from backend.ai.location_extractor import extract_location, get_place
from backend.models.incident import Incident
from backend.models.review_assistance import LocationConfirmation
from sqlalchemy import select
from backend.services.review_assistance import report_input_hash

DEFAULT_WINDOW_HOURS = 72
CONCEPTS = {
    "flood": ("flood", "flooding", "water rising", "വെള്ളപ്പൊക്ക", "പ്രളയ", "വെള്ളം കയറി"),
    "trapped": ("trapped", "stranded", "stuck", "കുടുങ്ങ", "ഒറ്റപ്പെട്ട"),
    "rescue": ("rescue", "evacuat", "save us", "രക്ഷിക്ക", "രക്ഷാ", "രക്ഷ വേണം"),
    "home": ("house", "home", "residence", "വീട്ട", "വീട്", "വീടു"),
    "roof": ("roof", "rooftop", "മേൽക്കൂര", "മട്ടുപ്പാവ"),
    "food": ("food", "meal", "ration", "ഭക്ഷണ", "ആഹാര"),
    "drinking_water": ("drinking water", "potable water", "കുടിവെള്ള"),
    "medical": ("medical", "medicine", "injured", "injury", "മരുന്ന", "ചികിത്സ", "പരിക്ക"),
    "children": ("child", "children", "kids", "കുട്ടി", "കുട്ടികൾ"),
    "elderly": ("elderly", "senior", "വയോധിക", "വൃദ്ധ"),
    "shelter": ("shelter", "relief camp", "അഭയ", "ദുരിതാശ്വാസ ക്യാമ്പ"),
    "landslide": ("landslide", "landslip", "മണ്ണിടിച്ച", "ഉരുൾപൊട്ട"),
    "road": ("road", "street", "റോഡ്", "റോഡ"),
    "bridge": ("bridge", "പാലം", "പാലത്ത"),
    "school": ("school", "സ്കൂൾ", "വിദ്യാലയ"),
    "power": ("electric", "power line", "വൈദ്യുത"),
}


def normalize(text):
    return " ".join(unicodedata.normalize("NFC", text or "").casefold().split())


def concepts(text):
    normalized = normalize(text)
    # English roots cover inflection, while Malayalam roots retain combining
    # marks. Word starts prevent 'road' matching unrelated English substrings.
    return {name for name, aliases in CONCEPTS.items() if any(
        (re.search(r"(?<![a-z])" + re.escape(alias), normalized) if alias.isascii() else alias in normalized)
        for alias in aliases)}


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def denied_facts(text):
    """Recognise explicit factual negation, without treating 'not enough food' as safe."""
    value = normalize(text)
    denied = set()
    english = {
        "trapped": r"(?:\b(?:not|isn't|aren't|wasn't|weren't|no longer)\s+(?:currently\s+)?(?:trapped|stranded)|\bno\s+(?:one|people|person|children|child)\s+(?:(?:is|are|was|were)\s+)?(?:trapped|stranded))",
        "flood": r"\b(?:no\s+(?:flood|flooding)|(?:not|isn't|aren't)\s+flooded)",
        "medical": r"(?:\bno\s+(?:one\s+is\s+injured|injuries)|\bnot\s+injured)",
    }
    for concept, pattern in english.items():
        if re.search(pattern, value):
            denied.add(concept)
    for concept, phrases in {"trapped": ("കുടുങ്ങിയിട്ടില്ല", "കുടുങ്ങിയില്ല", "ആരും കുടുങ്ങിയിട്ടില്ല"),
                             "flood": ("വെള്ളം കയറിയിട്ടില്ല", "വെള്ളപ്പൊക്കമില്ല", "പ്രളയമില്ല"),
                             "medical": ("പരിക്കില്ല", "പരിക്കേറ്റിട്ടില്ല")}.items():
        if any(phrase in value for phrase in phrases):
            denied.add(concept)
    return denied


def address_numbers(text):
    return set(re.findall(r"(?:\bhouse|\bbuilding|\bward|വീട്ടുനമ്പർ|വീട്|വാർഡ്)\s*(?:(?:no\.?|number|നമ്പർ|#)\s*)?(\d+[a-z]?(?:/\d+)?)", normalize(text)))


def confirmed_locations(db, *, incident_ids=None, start=None, end=None):
    """One batched query; ignore confirmations invalidated by changed inputs."""
    query = select(LocationConfirmation, Incident).join(Incident, Incident.id == LocationConfirmation.incident_id)
    if incident_ids is not None:
        query = query.where(Incident.id.in_(incident_ids))
    else:
        query = query.where(Incident.created_at >= start, Incident.created_at <= end)
    rows = db.execute(query.order_by(LocationConfirmation.id.desc()).execution_options(yield_per=200))
    result, hashes = {}, {}
    for confirmation, report in rows:
        if report.id in result:
            continue
        if report.id not in hashes:
            hashes[report.id] = report_input_hash(report)
        current_hash = hashes[report.id]
        if confirmation.input_hash != current_hash:
            continue
        place = get_place(confirmation.place_id)
        if place:
            result[report.id] = {"id": confirmation.id, "place": place, "locality": confirmation.locality,
                                 "created_at": confirmation.created_at, "input_hash": confirmation.input_hash}
    return result


def comparison_input_hash(report, confirmation=None):
    original_hash = report_input_hash(report)
    if confirmation is None:
        return original_hash
    return hashlib.sha256(json.dumps([original_hash, confirmation["id"], confirmation["place"].id,
                                      confirmation.get("locality")], ensure_ascii=False).encode()).hexdigest()


def location_match(first, second, *, first_message="", second_message="", first_confirmation=None, second_confirmation=None):
    left = extract_location(first_message, first)
    right = extract_location(second_message, second)
    left_place = first_confirmation["place"] if first_confirmation else left.place
    right_place = second_confirmation["place"] if second_confirmation else right.place
    if left_place and right_place:
        if left_place.district_id != right_place.district_id:
            return None
        if left_place.kind == right_place.kind == "locality":
            if left_place.id != right_place.id:
                return None
            source = "human-confirmed" if first_confirmation or second_confirmation else "gazetteer"
            return f"Same {source} locality: {left_place.name}, {left_place.district} (known aliases included)."
    if first_confirmation or second_confirmation:
        # A district confirmation cannot make every event in that district a
        # duplicate. Require agreeing locality text and retain its uncertainty.
        if not left_place or not right_place:
            return None
        left_text = normalize(first_confirmation.get("locality") or first) if first_confirmation else normalize(first)
        right_text = normalize(second_confirmation.get("locality") or second) if second_confirmation else normalize(second)
        if not left_text or left_text != right_text:
            return None
        district_only_names = {normalize(alias) for p in (left_place, right_place) if p.kind == "district"
                               for alias in [p.name, *p.aliases]}
        if left_text in district_only_names:
            return None
        return f"Same confirmed district: {left_place.district}; same unverified locality text. Locality identity still requires review."
    # A repeated ambiguous alias such as Paravur cannot establish a locality.
    if ((left.status == "UNCERTAIN" and left.candidates) or (right.status == "UNCERTAIN" and right.candidates)):
        return None
    if normalize(first) and normalize(first) == normalize(second):
        return "Same written location; locality/district still needs confirmation." if left.status == "UNCERTAIN" else "Same reported location."
    return None


def compare_reports(first, second, window_hours=DEFAULT_WINDOW_HOURS, *, first_confirmation=None, second_confirmation=None):
    gap = abs((utc(first.created_at) - utc(second.created_at)).total_seconds()) / 3600
    if gap > window_hours:
        return None
    location_reason = location_match(first.location, second.location, first_message=first.message, second_message=second.message,
                                     first_confirmation=first_confirmation, second_confirmation=second_confirmation)
    if not location_reason:
        return None
    first_text, second_text = normalize(first.message), normalize(second.message)
    if not first_text or not second_text:
        return None
    lexical = SequenceMatcher(None, first_text, second_text, autojunk=False).ratio()
    left, right = concepts(first_text), concepts(second_text)
    left_denied, right_denied = denied_facts(first_text), denied_facts(second_text)
    if (left_denied & (right - right_denied)) or (right_denied & (left - left_denied)):
        return None
    left_addresses = address_numbers(first_text + " " + first.location)
    right_addresses = address_numbers(second_text + " " + second.location)
    if left_addresses and right_addresses and left_addresses.isdisjoint(right_addresses):
        return None
    common = left & right
    semantic = 2 * len(common) / (len(left) + len(right)) if left and right else 0
    # Common flood wording alone cannot support a multilingual match.
    semantic_match = semantic >= .75 and len(common - {"flood"}) >= 2
    if lexical < .65 and not semantic_match:
        return None
    score = max(lexical, semantic * .95 if semantic_match else 0)
    reasons = [location_reason, f"Submitted {gap:.1f} hours apart (within {window_hours} hours)."]
    if lexical >= .65:
        reasons.append(f"Similar report wording ({lexical:.0%}).")
    if semantic_match:
        reasons.append("Shared English/Malayalam incident concepts: " + ", ".join(sorted(common)).replace("_", " ") + ".")
    return {"id": second.id, "report_reference": second.report_reference, "location": second.location,
            "message": second.message, "status": second.status, "created_at": second.created_at,
            "people_affected": second.people_affected, "help_required": second.help_required,
            "similarity": round(score, 3), "text_similarity": round(lexical, 3),
            "semantic_similarity": round(semantic, 3), "time_gap_hours": round(gap, 2),
            "reasons": reasons, "source_hash": comparison_input_hash(first, first_confirmation),
            "candidate_hash": comparison_input_hash(second, second_confirmation),
            "method": "gazetteer_aliases+time_window+bilingual_event_concepts"}
