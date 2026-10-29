from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, select
from backend.models.incident import Incident
from backend.models.week4_analysis import Week4AnalysisRevision

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
    user: User = Depends(require_roles(Role.ADMIN)),
    use_ai: bool = True,
):
   

    incident = get_incident_by_id(db, incident_id)

    if incident is None:
        raise HTTPException(
            status_code=404,
            detail="Incident not found.",
        )

    result = await run_week4_workflow(db, incident, use_ai=use_ai)

    
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

    # Serialize revision assignment for this incident on PostgreSQL. Model
    # calls happen before the lock so they do not hold up response operations.
    db.scalar(select(Incident.id).where(Incident.id == incident_id).with_for_update())
    revision = (db.scalar(select(func.max(Week4AnalysisRevision.revision)).where(
        Week4AnalysisRevision.incident_id == incident_id)) or 0) + 1
    result["revision"] = revision
    validated = Week4WorkflowResponse.model_validate(result)
    db.add(Week4AnalysisRevision(incident_id=incident_id, revision=revision,
                                 created_by=user.id, result=validated.model_dump(mode="json")))
    db.commit()
    return validated


@router.get("/{incident_id}/week4-analysis")
def analysis_history(incident_id: int, db: Session = Depends(get_db),
                     user: User = Depends(require_roles(Role.ADMIN))):
    if get_incident_by_id(db, incident_id) is None:
        raise HTTPException(status_code=404, detail="Incident not found.")
    rows = db.scalars(select(Week4AnalysisRevision).where(
        Week4AnalysisRevision.incident_id == incident_id).order_by(Week4AnalysisRevision.revision.desc()))
    return [{"revision": row.revision, "created_at": row.created_at,
             "created_by": row.created_by, "result": row.result} for row in rows]