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


@lru_cache(maxsize=1)
def get_pipeline():
    # Loading on the first request lets the rest of ResQ remain available if
    # the model artifact or one of its scientific dependencies is missing.
    import joblib

    return joblib.load(MODEL_PATH)


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def predict_severity(message: str) -> str:
    try:
        prediction = str(get_pipeline().predict([clean_text(message)])[0])
        if prediction not in SEVERITY_LABELS:
            raise ValueError("The model returned an unsupported severity label")
        return prediction
    except Exception as error:
        logger.exception("The flood severity model could not produce a prediction")
        raise SeverityUnavailable("Severity prediction is temporarily unavailable.") from error
