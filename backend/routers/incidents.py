from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from backend.models.report_analysis import ReportAnalysis
from backend.database.connection import get_db
from backend.models import Role, User
from backend.schemas.incident_schema import (
    IncidentCreate,
    IncidentResponse,
    IncidentHistoryResponse,
    IncidentStatusUpdate,
    ClarificationRequest,
    ClarificationResponse,
    CaseClosureRequest,
)
from backend.schemas.team_schema import AssignTeamRequest
from backend.services.incident_service import (
    create_incident,
    get_my_incidents,
    get_incident_by_id,
    get_incident_history,
    review_incident,
    assign_incident_team,
    get_latest_report_analysis,
    request_clarification,
respond_to_clarification,
close_incident,
)
from backend.utils.permissions import get_current_user, require_roles
from backend.utils.validators import validate_incident_owner


router = APIRouter(prefix="/api/incidents", tags=["Incidents"])


def accessible_incident(db: Session, incident_id: int, user: User):
    incident = get_incident_by_id(db=db, incident_id=incident_id)

    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")

    is_owner = (
        user.role == Role.CITIZEN
        and validate_incident_owner(incident.user_id, user.id)
    )

    is_assigned_team = (
        user.role == Role.RESPONSE_TEAM
        and user.team_id is not None
        and incident.assigned_team_id == user.team_id
    )

    if not (is_owner or user.role == Role.ADMIN or is_assigned_team):
        raise HTTPException(
            status_code=403,
            detail="You are not allowed to access this incident",
        )

    return incident


@router.post(
    "/",
    response_model=IncidentResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_incident_api(
    data: IncidentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(Role.CITIZEN)),
):
    return create_incident(
        db=db,
        user_id=user.id,
        **data.model_dump(),
    )


@router.get("/", response_model=list[IncidentResponse])
@router.get("/my", response_model=list[IncidentResponse])
def my_incidents(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(Role.CITIZEN)),
):
    return get_my_incidents(db=db, user_id=user.id)


@router.get("/{incident_id}", response_model=IncidentResponse)
def incident_detail(
    incident_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return accessible_incident(db, incident_id, user)


@router.get(
    "/{incident_id}/history",
    response_model=list[IncidentHistoryResponse],
)
def incident_history(
    incident_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    accessible_incident(db, incident_id, user)

    return get_incident_history(
        db=db,
        incident_id=incident_id,
    )


@router.get("/{incident_id}/status")
def incident_status(
    incident_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    incident = accessible_incident(db, incident_id, user)

    return {
        "incident_id": incident.id,
        "status": incident.status,
    }
@router.get("/{incident_id}/analysis")
def incident_analysis(
    incident_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    incident = accessible_incident(db, incident_id, user)

    analysis = get_latest_report_analysis(db, incident.id)

    if analysis is None:
        raise HTTPException(
            status_code=404,
            detail="Analysis not found for this incident",
        )

    return {
        "id": analysis.id,
        "incident_id": analysis.incident_id,
        "summary": analysis.summary,
        "summary_is_provisional": analysis.summary_is_provisional,
        "requires_manual_review": analysis.requires_manual_review,
        "created_at": analysis.created_at,
    }


@router.patch(
    "/{incident_id}/status",
    response_model=IncidentResponse,
)
def update_incident_status(
    incident_id: int,
    data: IncidentStatusUpdate,
    db: Session = Depends(get_db),
    _user: User = Depends(require_roles(Role.ADMIN)),
):
    return review_incident(
        db,
        incident_id,
        data.status,
        data.note,
    )


@router.post(
    "/admin/assign-team",
    response_model=IncidentResponse,
)
def assign_team_to_incident(
    data: AssignTeamRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(require_roles(Role.ADMIN)),
):
    incident = assign_incident_team(
        db=db,
        incident_id=data.incident_id,
        team_id=data.team_id,
        assignment_note=data.assignment_note,
    )

    if incident is None:
        raise HTTPException(
            status_code=400,
            detail="Incident or available team not found",
        )

    return incident
@router.post("/{incident_id}/clarification")
def request_incident_clarification(
    incident_id: int,
    data: ClarificationRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(Role.ADMIN)),
):
    incident = request_clarification(
        db=db,
        incident_id=incident_id,
        admin_id=user.id,
        message=data.message,
    )
    return {
        "message": "Clarification requested successfully",
        "incident": incident,
    }


@router.post("/{incident_id}/clarification/respond")
def respond_incident_clarification(
    incident_id: int,
    data: ClarificationResponse,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(Role.CITIZEN)),
):
    incident = respond_to_clarification(
        db=db,
        incident_id=incident_id,
        user_id=user.id,
        message=data.message,
    )
    return {
        "message": "Clarification response recorded successfully",
        "incident": incident,
    }


@router.post("/{incident_id}/close")
def close_incident_api(
    incident_id: int,
    data: CaseClosureRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(Role.ADMIN)),
):
    incident = close_incident(
        db=db,
        incident_id=incident_id,
        admin_id=user.id,
        reason=data.reason,
    )
    return {
        "message": "Incident closed successfully",
        "incident": incident,
    }