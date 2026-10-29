from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from backend.ai.severity_model import SeverityUncertain, SeverityUnavailable, assess_severity, predict_severity
from backend.database.connection import get_db
from backend.models import Role, User
from backend.schemas.investigation_schema import AnalysisResponse
from backend.services.investigation_service import require_incident, save_predicted_severity
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


@router.post("/incidents/{incident_id}/predict-severity", response_model=AnalysisResponse)
def predict_incident_severity(incident_id: int, db: Session = Depends(get_db),
                              user: User = Depends(require_roles(Role.ADMIN))):
    incident = require_incident(db, incident_id)
    try:
        severity = predict_severity(incident.message)
    except SeverityUncertain as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except SeverityUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return save_predicted_severity(db, incident_id, user.id,
                                  {"High": "HIGH", "Moderate": "MEDIUM", "Low": "LOW"}[severity])
