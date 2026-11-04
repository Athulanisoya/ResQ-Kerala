from typing import Literal
import hashlib

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from backend.ai.severity_model import SeverityUncertain, SeverityUnavailable, assess_severity, get_model_version, predict_severity
from backend.database.connection import get_db
from backend.models import Role, User
from backend.schemas.severity_prediction_schema import SeverityDecisionRequest, SeverityPredictionResponse
from backend.services.investigation_service import (require_incident, save_predicted_severity,
                                                   severity_predictions, review_predicted_severity)
from backend.utils.permissions import require_roles


router = APIRouter(prefix="/api/ai", tags=["AI Severity Prediction"])


class SeverityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    message: str = Field(min_length=5, max_length=5000)


class SeverityResponse(BaseModel):
    message: str
    predicted_severity: Literal["High", "Low", "Moderate"]
    model_score: float | None = None
    requires_manual_review: bool = True


@router.post("/predict-severity", response_model=SeverityResponse,
             dependencies=[Depends(require_roles(Role.ADMIN))])
def predict_flood_severity(request: SeverityRequest):
    try:
        result = assess_severity(request.message)
    except SeverityUncertain as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except SeverityUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return {"message": request.message, **result}


@router.post("/incidents/{incident_id}/predict-severity", response_model=SeverityPredictionResponse)
def predict_incident_severity(incident_id: int, db: Session = Depends(get_db),
                              user: User = Depends(require_roles(Role.ADMIN))):
    incident = require_incident(db, incident_id)
    try:
        severity = predict_severity(incident.message)
        model_version = get_model_version()
    except SeverityUncertain as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except SeverityUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return save_predicted_severity(db, incident_id, user.id,
                                  {"High": "HIGH", "Moderate": "MEDIUM", "Low": "LOW"}[severity],
                                  model_version=model_version,
                                  input_hash=hashlib.sha256(incident.message.encode("utf-8")).hexdigest())


@router.get("/incidents/{incident_id}/severity-predictions", response_model=list[SeverityPredictionResponse])
def list_severity_predictions(incident_id: int, db: Session = Depends(get_db),
                              user: User = Depends(require_roles(Role.ADMIN))):
    return severity_predictions(db, incident_id)


@router.post("/incidents/{incident_id}/severity-predictions/{prediction_id}/review",
             response_model=SeverityPredictionResponse)
def review_severity_prediction(incident_id: int, prediction_id: int, request: SeverityDecisionRequest,
                               db: Session = Depends(get_db),
                               user: User = Depends(require_roles(Role.ADMIN))):
    return review_predicted_severity(db, incident_id, prediction_id, user.id, request)
