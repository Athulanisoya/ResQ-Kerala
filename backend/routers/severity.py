from fastapi import APIRouter
from pydantic import BaseModel

from backend.ai.severity_model import predict_severity

router = APIRouter(
    prefix="/api/ai",
    tags=["AI Severity Prediction"]
)

class SeverityRequest(BaseModel):
    message: str

@router.post("/predict-severity")
def predict_flood_severity(request: SeverityRequest):
    severity = predict_severity(request.message)

    return{
        "message": request.message,
        "predicted_severity": severity
    }