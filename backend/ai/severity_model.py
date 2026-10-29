"""Run the Week 2 flood severity model without blocking application startup."""

from functools import lru_cache
import logging
from pathlib import Path
import re


MODEL_PATH = Path(__file__).resolve().with_name("pipeline.joblib")
SEVERITY_LABELS = frozenset({"High", "Low", "Moderate"})
logger = logging.getLogger(__name__)


class SeverityUnavailable(RuntimeError):
    """The saved model cannot currently produce a valid prediction."""


class SeverityUncertain(SeverityUnavailable):
    """The input is outside the model's demonstrated safe operating range."""


_NEGATION = re.compile(r"\b(?:no|not|never|none|nobody|without|neither|nor|isn't|aren't|wasn't|weren't|don't|doesn't|didn't)\b", re.IGNORECASE)
_MALAYALAM = re.compile(r"[\u0d00-\u0d7f]")


@lru_cache(maxsize=1)
def get_pipeline():
    # Loading on the first request lets the rest of ResQ remain available if
    # the model artifact or one of its scientific dependencies is missing.
    import joblib

    return joblib.load(MODEL_PATH)


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def assess_severity(message: str) -> dict:
    """Return a model score, not a calibrated probability of real-world urgency.

    Negation and Malayalam are deliberately referred for manual review until
    validated language-specific models are available. Out-of-vocabulary input
    cannot support a meaningful TF-IDF classification.
    """
    cleaned = clean_text(message)
    if _MALAYALAM.search(cleaned):
        raise SeverityUncertain("Malayalam text requires translation and manual severity review.")
    if _NEGATION.search(cleaned):
        raise SeverityUncertain("Negation requires manual severity review; the model may misinterpret it.")
    try:
        pipeline = get_pipeline()
        vectorizer = getattr(pipeline, "named_steps", {}).get("tfidf")
        if vectorizer is not None and vectorizer.transform([cleaned]).nnz == 0:
            raise SeverityUncertain("The message is outside the model vocabulary; manual severity review is required.")
        prediction = str(pipeline.predict([cleaned])[0])
        if prediction not in SEVERITY_LABELS:
            raise ValueError("The model returned an unsupported severity label")
        score = None
        if hasattr(pipeline, "predict_proba"):
            probabilities = pipeline.predict_proba([cleaned])[0]
            labels = list(pipeline.classes_)
            score = float(probabilities[labels.index(prediction)])
        return {"predicted_severity": prediction, "model_score": score,
                "requires_manual_review": True}
    except SeverityUncertain:
        raise
    except Exception as error:
        logger.exception("The flood severity model could not produce a prediction")
        raise SeverityUnavailable("Severity prediction is temporarily unavailable.") from error


def predict_severity(message: str) -> str:
    return assess_severity(message)["predicted_severity"]
