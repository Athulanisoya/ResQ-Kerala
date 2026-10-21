"""Create a bounded draft by selecting original report text, entirely offline.

This is local extraction, not a generative model. It does not determine whether
a report is true or infer casualty counts, urgency, or response decisions.
"""

import hashlib
import json
import re


METHOD = "local_extractive_v1"
METHOD_LABEL = "Local extractive draft"
MAX_SUMMARY_LENGTH = 1200
SOURCE_FIELDS = ("message", "location", "people_affected", "help_required", "disaster_type")

# Matching only chooses excerpts. Both affirmative and negated statements are
# copied intact; matching "injured" does not assert that anyone was injured.
_URGENT = re.compile(
    r"\b(?:trapped|stranded|drowning|unconscious|missing|injur\w*|dead|death\w*|"
    r"casualt\w*|rescue|evacuat\w*|medical|urgent|emergency|children|child|"
    r"elderly|pregnant|breathing|collapsed|collapse|swept)\b|"
    r"കുടുങ്ങ|രക്ഷ|പരിക്ക|മരണ|മരിച്ച|കാണാത|കുട്ടി|അടിയന്തിര|ഗർഭിണി",
    re.IGNORECASE,
)
_NEGATION = re.compile(r"\b(?:no|not|never|none|nobody|without|neither|nor|isn't|aren't|wasn't|weren't|don't|doesn't|didn't)\b|ഇല്ല|അല്ല|വേണ്ട|ആയിട്ടില്ല", re.IGNORECASE)


def _text(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def input_hash(incident) -> str:
    source = {name: getattr(incident, name, None) for name in SOURCE_FIELDS}
    encoded = json.dumps(source, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _score(sentence: str) -> int:
    return len(_URGENT.findall(sentence))


def _fit_sentence(sentence: str, budget: int) -> str:
    """Prefer complete clauses when a single sentence exceeds the space left.

    A clause following a negated clause retains that context. An unbroken long
    sentence with distant negation is kept as a prefix, instead of dropping its
    negation and turning a casualty statement into an affirmative claim.
    """
    if len(sentence) <= budget:
        return sentence
    clauses = re.split(r"(?<=[;,])\s+", sentence)
    if len(clauses) > 1:
        ranked = sorted(range(len(clauses)), key=lambda index: (-_score(clauses[index]), index))
        for index in ranked:
            start = index
            # Negation can govern a later list item: "No one is injured;
            # trapped; or missing." Retain the preceding negation verbatim.
            preceding = [i for i in range(index) if _NEGATION.search(clauses[i])]
            if preceding:
                start = preceding[-1]
            candidate = " ".join(clauses[start:index + 1]).strip()
            if len(candidate) <= budget:
                return ("… " if start else "") + candidate if len(candidate) + (2 if start else 0) <= budget else candidate
    # For a long, punctuation-free passage without negation, take a quoted
    # partial excerpt around the last urgent clause instead of its first words.
    urgent = list(_URGENT.finditer(sentence))
    if urgent and not _NEGATION.search(sentence):
        start = max(0, urgent[-1].start() - max(40, budget // 3))
        if start:
            next_space = sentence.find(" ", start)
            start = next_space + 1 if next_space >= 0 else start
        fragment = sentence[start:start + max(0, budget - 4)]
        if len(fragment) < len(sentence) - start and " " in fragment:
            fragment = fragment.rsplit(" ", 1)[0]
        return ("… " if start else "") + fragment + " …"
    fragment = sentence[:max(0, budget - 2)]
    if " " in fragment:
        fragment = fragment.rsplit(" ", 1)[0]
    return fragment + " …"


def summarize_report(incident) -> str:
    facts = []
    if getattr(incident, "location", None):
        facts.append(f"Reported location: {_text(incident.location)}.")
    if getattr(incident, "people_affected", None) is not None:
        facts.append(f"People affected (reported): {incident.people_affected}.")
    if getattr(incident, "help_required", None):
        facts.append(f"Help requested: {_text(incident.help_required)}.")
    prefix = " ".join(facts)
    # A visual line wrap may separate "No one was" from "injured". Normalize
    # it within the sentence so ranking never drops the negation fragment.
    message = _text(getattr(incident, "message", ""))
    sentences = [_text(part) for part in re.split(r"(?<=[.!?।])\s+", message) if _text(part)]
    sentences = list(dict.fromkeys(sentences))
    if not sentences:
        return prefix[:MAX_SUMMARY_LENGTH]
    # The schema bounds location/help fields to 255 characters each. Keep a
    # fixed details budget even if a caller bypasses that schema.
    prefix = prefix[:650].rstrip()
    details_label = " Report excerpts: " if prefix else "Report excerpts: "
    remaining = MAX_SUMMARY_LENGTH - len(prefix) - len(details_label)
    ranked = sorted(range(len(sentences)), key=lambda index: (-_score(sentences[index]), index))
    selected = {}
    for index in ranked:
        if len(selected) == 3 or remaining < 35:
            break
        sentence = sentences[index]
        # Do not let a long routine passage displace a shorter urgent passage.
        if len(sentence) > remaining and selected:
            continue
        excerpt = _fit_sentence(sentence, remaining)
        selected[index] = excerpt
        remaining -= len(excerpt) + 1
    return (prefix + details_label + " ".join(selected[index] for index in sorted(selected)))[:MAX_SUMMARY_LENGTH]
