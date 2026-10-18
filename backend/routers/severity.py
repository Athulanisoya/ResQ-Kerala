from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from backend.ai.severity_model import SeverityUnavailable, predict_severity
from backend.models import Role
from backend.utils.permissions import require_roles


router = APIRouter(prefix="/api/ai", tags=["AI Severity Prediction"])


class SeverityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    message: str = Field(min_length=5, max_length=5000)


class SeverityResponse(BaseModel):
    message: str
    predicted_severity: Literal["High", "Low", "Moderate"]


@router.post("/predict-severity", response_model=SeverityResponse,
             dependencies=[Depends(require_roles(Role.ADMIN))])
def predict_flood_severity(request: SeverityRequest):
    try:
        severity = predict_severity(request.message)
    except SeverityUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return {"message": request.message, "predicted_severity": severity}
