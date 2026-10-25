from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.ai.week4_orchestrator import run_week4_workflow
from backend.database.connection import get_db
from backend.models import Role, User
from backend.schemas.week4_schema import Week4WorkflowResponse
from backend.services.incident_service import get_incident_by_id
from backend.utils.permissions import require_roles
router = APIRouter(prefix="/api/incidents",tags=["Week 4 AI Orchestration"])
@router.post("/{incident_id}/week4-analysis",response_model=Week4WorkflowResponse)
async def analyze_incident_week4(
    incident_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(require_roles(Role.ADMIN)),
):
   

    incident = get_incident_by_id(db, incident_id)

    if incident is None:
        raise HTTPException(
            status_code=404,
            detail="Incident not found.",
        )

    result = await run_week4_workflow(db, incident)

    
    if result.get("status") == "complete":
        required_tools = [
            "tool_1_extract_location",
            "tool_2_check_alerts",
            "tool_3_predict_severity",
            "tool_4_create_summary",
            "tool_5_retrieve_safety_evidence",
            "tool_6_search_shelters",
        ]

        results = result.get("results", {})
        missing = [
            name for name in required_tools
            if name not in results
        ]

        if missing:
            result["status"] = "incomplete"
            result["missing_tools"] = missing

    return Week4WorkflowResponse.model_validate(result)