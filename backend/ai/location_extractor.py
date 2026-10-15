"""Conservative, offline location extraction from a curated Kerala gazetteer.

This is a deterministic tool, not an LLM geocoder. It resolves only explicit
whole aliases, never estimates coordinates, and preserves uncertainty when
reports name different places or an alias exists in more than one district.
The gazetteer intentionally covers a limited set of localities, not all Kerala.
"""

from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path
import re
import unicodedata

from backend.schemas.location_schema import LocationExtraction, Place


GAZETTEER_PATH = Path(__file__).resolve().parents[2] / "data" / "raw" / "kerala_gazetteer.json"


@lru_cache(maxsize=1)
def _places() -> tuple[Place, ...]:
    data = json.loads(GAZETTEER_PATH.read_text(encoding="utf-8"))
    places = tuple(Place.model_validate(item) for item in data["places"])
    if len({place.id for place in places}) != len(places):
        raise ValueError("The Kerala gazetteer contains duplicate place IDs.")
    districts = {place.id for place in places if place.kind == "district"}
    if any(place.district_id not in districts for place in places):
        raise ValueError("A gazetteer place references an unknown district.")
    return places


def list_places() -> list[Place]:
    """Return the curated places, including provenance and known aliases."""
    return [place.model_copy(deep=True) for place in _places()]


def get_place(place_id: str) -> Place | None:
    """Look up an exact stable ID. Unknown IDs never become guessed places."""
    place = next((place for place in _places() if place.id == place_id), None)
    return place.model_copy(deep=True) if place is not None else None


def _normalise(text: str) -> str:
    # NFC keeps Malayalam combining sequences intact; ZW characters are common
    # copy/paste artifacts and do not distinguish aliases in this curated list.
    return unicodedata.normalize("NFC", text).translate({0x200B: None, 0x200C: None, 0x200D: None, 0xFEFF: None})


@lru_cache(maxsize=512)
def _pattern(alias: str) -> re.Pattern[str]:
    words = re.split(r"[\s-]+", _normalise(alias).strip())
    return re.compile(r"(?<!\w)" + r"[\s-]+".join(re.escape(word) for word in words) + r"(?!\w)", re.IGNORECASE)


@dataclass(frozen=True)
class _Match:
    place: Place
    start: int
    end: int
    text: str


def _matches(text: str) -> list[_Match]:
    text = _normalise(text)

    def word_character(character: str) -> bool:
        return character == "_" or unicodedata.category(character)[0] in {"L", "M", "N"}

    matches = [
        _Match(place, match.start(), match.end(), match.group())
        for place in _places()
        for alias in dict.fromkeys([place.name, *place.aliases])
        for match in _pattern(alias).finditer(text)
        # Python's \w excludes combining marks. Treat them as word characters
        # too, so a Malayalam alias cannot match a fragment of a longer word.
        if (match.start() == 0 or not word_character(text[match.start() - 1]))
        and (match.end() == len(text) or not word_character(text[match.end()]))
    ]
    # "North Paravur" is one alias; its nested "Paravur" must not create
    # candidates in other districts. Equal spans deliberately retain ambiguity.
    return [
        match for match in matches
        if not any(other.start <= match.start and other.end >= match.end
                   and (other.end - other.start) > (match.end - match.start)
                   for other in matches)
    ]


def _unique_places(matches: list[_Match]) -> list[Place]:
    return sorted({match.place.id: match.place for match in matches}.values(), key=lambda place: place.id)


def extract_location(message: str, reported_location: str | None = None) -> LocationExtraction:
    """Resolve explicit place aliases from a report and its location field.

    A district may disambiguate an identical locality name, including when the
    qualifier is in the other field. Different localities remain uncertain even
    within one district. A district-only match has district-level precision;
    it makes no claim that an unrecognised street or locality was verified.
    Report content is always data and cannot change these matching rules.
    """
    message_matches = _matches(message or "")
    reported_matches = _matches(reported_location or "")
    matches = message_matches + reported_matches
    places = _unique_places(matches)
    matched_text = list(dict.fromkeys(match.text for match in matches))
    districts = [place for place in places if place.kind == "district"]
    localities = [place for place in places if place.kind == "locality"]

    def result(status: str, candidates: list[Place], reason: str) -> LocationExtraction:
        safe_candidates = [place.model_copy(deep=True) for place in candidates]
        return LocationExtraction(
            status=status,
            place=safe_candidates[0].model_copy(deep=True) if status == "RESOLVED" else None,
            candidates=safe_candidates,
            matched_text=matched_text,
            reason=reason,
        )

    if not places:
        return result("UNCERTAIN", [], "No whole place alias matched the curated, incomplete Kerala gazetteer. Clarify the locality and district.")
    if reported_location and reported_location.strip() and not reported_matches:
        return result("UNCERTAIN", places, "The explicit location field is not recognised by the curated gazetteer. Message matches cannot verify that location; clarify the locality and district.")
    if len(districts) > 1:
        return result("UNCERTAIN", places, "The report and location field name multiple districts. Clarify the incident location.")
    if districts and localities:
        district_id = districts[0].id
        qualified = [place for place in localities if place.district_id == district_id]
        # Do not discard a uniquely named locality that conflicts with the
        # qualifier. Discarding is safe only for alternatives to the same alias.
        outside = [match for match in matches if match.place.kind == "locality" and match.place.district_id != district_id]
        unsupported = [match for match in outside if not any(
            inside.place.kind == "locality" and inside.place.district_id == district_id
            and _normalise(inside.text).casefold() == _normalise(match.text).casefold()
            for inside in matches
        )]
        if not qualified or unsupported:
            return result("UNCERTAIN", places, "A matched locality conflicts with the reported district. Clarify the incident location.")
        localities = qualified
    if len(localities) == 1:
        return result("RESOLVED", localities, "One explicit locality matched the curated gazetteer" + (" within the named district." if districts else "."))
    if len(localities) > 1:
        return result("UNCERTAIN", localities, "Multiple localities match. Supply a district for a repeated name or clarify which locality is affected.")
    return result("RESOLVED", districts, "Only the district is resolved; any unrecognised locality or street still requires clarification.")
