from datetime import datetime
from uuid import uuid4
from backend.models.notification import Notification

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from backend.models.incident import Incident, IncidentStatusHistory
from backend.models.report_analysis import ReportAnalysis
from backend.models.team import Team
from backend.ai.summarizer import summarize_report


def generate_report_reference(db: Session):
    return f"RESQ {datetime.now():%Y%m%d} {uuid4().hex.upper()}"


def create_incident(
    db: Session,
    user_id: int,
    message: str,
    location: str,
    people_affected=None,
    help_required=None,
    disaster_type="Flood",
):
    incident = Incident(
        report_reference=generate_report_reference(db),
        user_id=user_id,
        message=message,
        location=location,
        people_affected=people_affected,
        help_required=help_required,
        disaster_type=disaster_type,
        status="SUBMITTED",
    )

    try:
        # Save the incident temporarily to obtain its database ID.
        db.add(incident)
        db.flush()

        # Generate the AI summary. The summarizer handles its own
        # failures and returns a provisional fallback when necessary.
        analysis_result = summarize_report(message)

        # Save the analysis separately from the original incident.
        analysis = ReportAnalysis(
            incident_id=incident.id,
            summary=analysis_result["summary"],
            summary_is_provisional=analysis_result["is_provisional"],
            requires_manual_review=analysis_result["requires_manual_review"],
        )

        db.add(analysis)

        # Preserve the existing incident status history workflow.
        db.add(
            IncidentStatusHistory(
                incident_id=incident.id,
                status="SUBMITTED",
                note="Incident report submitted",
            )
        )

        # Athul's local checks run in the report transaction; Gemini is an
        # explicit admin action and never delays citizen submission.
        from backend.services.location_analysis_service import analyze_new_incident
        analyze_new_incident(db, incident)

        # Save a local report summary in the same transaction, independently
        # of the administrator's reviewed assessment and optional providers.
        from backend.services.summary_service import save_summary
        save_summary(db, incident, user_id)

        db.commit()

    except Exception:
        db.rollback()
        raise

    db.refresh(incident)
    return incident


def get_my_incidents(db: Session, user_id: int):
    return (
        db.query(Incident)
        .filter(Incident.user_id == user_id)
        .order_by(Incident.created_at.desc(), Incident.id.desc())
        .all()
    )


def get_incident_by_id(db: Session, incident_id: int):
    return db.get(Incident, incident_id)
def get_latest_report_analysis(db: Session, incident_id: int):
    return db.scalar(
        select(ReportAnalysis)
        .where(ReportAnalysis.incident_id == incident_id)
        .order_by(
            ReportAnalysis.created_at.desc(),
            ReportAnalysis.id.desc(),
        )
        .limit(1)
    )


def get_incident_history(db: Session, incident_id: int):
    return (
        db.query(IncidentStatusHistory)
        .filter(IncidentStatusHistory.incident_id == incident_id)
        .order_by(
            IncidentStatusHistory.created_at.asc(),
            IncidentStatusHistory.id.asc(),
        )
        .all()
    )


def review_incident(
    db: Session,
    incident_id: int,
    status: str,
    note: str | None,
):
    incident = db.scalar(
        select(Incident)
        .where(Incident.id == incident_id)
        .with_for_update()
    )

    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")

    allowed = {
        "SUBMITTED": {"UNDER_REVIEW", "VERIFIED"},
        "UNDER_REVIEW": {"VERIFIED"},
    }

    if status not in allowed.get(incident.status, set()):
        raise HTTPException(
            status_code=409,
            detail="This report cannot move to that review status.",
        )

    incident.status = status

    db.add(
        IncidentStatusHistory(
            incident_id=incident.id,
            status=status,
            note=note or "Admin reviewed the incident report",
        )
    )

    db.commit()
    db.refresh(incident)
    return incident


def assign_incident_team(
    db: Session,
    incident_id: int,
    team_id: int,
    assignment_note: str | None = None,
):
    """
    Assign an available response team to a verified incident.
    """

    try:
        # Lock the incident to prevent simultaneous assignments.
        incident = db.scalar(
            select(Incident)
            .where(Incident.id == incident_id)
            .with_for_update()
        )

        if incident is None:
            raise HTTPException(status_code=404, detail="Incident not found")

        if incident.status != "VERIFIED" or incident.assigned_team_id is not None:
            raise HTTPException(status_code=409, detail="Only a verified, unassigned report can be assigned.")

        # Lock the selected team while checking availability.
        team = db.scalar(
            select(Team)
            .where(Team.id == team_id)
            .with_for_update()
        )

        if team is None:
            raise HTTPException(status_code=404, detail="Response team not found")

        if team.status != "AVAILABLE":
            raise HTTPException(status_code=409, detail="This response team is already assigned.")

        team.status = "BUSY"
        incident.assigned_team_id = team.id
        incident.status = "ASSIGNED"

        db.add(
            IncidentStatusHistory(
                incident_id=incident.id,
                status="ASSIGNED",
                note=assignment_note or f"Team {team.name} assigned",
            )
        )

        db.commit()
        db.refresh(incident)

        return incident

    except Exception:
        db.rollback()
        raise


def assign_team(db: Session, incident_id: int, team_id: int):
    """Compatibility entry point for the existing admin API and validation tools."""
    return assign_incident_team(db, incident_id, team_id)

def request_clarification(
    db: Session,
    incident_id: int,
    admin_id: int,
    message: str,
):
    """Request additional information from the reporting citizen."""
    try:
        incident = db.scalar(
            select(Incident)
            .where(Incident.id == incident_id)
            .with_for_update()
        )

        if incident is None:
            raise HTTPException(status_code=404, detail="Incident not found")

        if incident.status in {"CLOSED", "RESOLVED"}:
            raise HTTPException(
                status_code=409,
                detail="Cannot request clarification for a closed incident.",
            )

        incident.status = "AWAITING_CLARIFICATION"

        db.add(
            IncidentStatusHistory(
                incident_id=incident.id,
                status="AWAITING_CLARIFICATION",
                note=f"Clarification requested by admin {admin_id}: {message}",
            )
        )

        db.add(
            Notification(
                user_id=incident.user_id,
                incident_id=incident.id,
                notification_type="CLARIFICATION_REQUEST",
                message=message,
            )
        )

        db.commit()
        db.refresh(incident)
        return incident

    except Exception:
        db.rollback()
        raise


def respond_to_clarification(
    db: Session,
    incident_id: int,
    user_id: int,
    message: str,
):
    """Record the reporting citizen's clarification response."""
    try:
        incident = db.scalar(
            select(Incident)
            .where(Incident.id == incident_id)
            .with_for_update()
        )

        if incident is None:
            raise HTTPException(status_code=404, detail="Incident not found")

        if incident.user_id != user_id:
            raise HTTPException(
                status_code=403,
                detail="Only the reporting citizen can respond.",
            )

        if incident.status != "AWAITING_CLARIFICATION":
            raise HTTPException(
                status_code=409,
                detail="This incident is not awaiting clarification.",
            )

        incident.status = "UNDER_REVIEW"

        db.add(
            IncidentStatusHistory(
                incident_id=incident.id,
                status="UNDER_REVIEW",
                note=f"Citizen clarification response: {message}",
            )
        )

        db.add(
            Notification(
                user_id=user_id,
                incident_id=incident.id,
                notification_type="CLARIFICATION_RESPONSE",
                message="Your clarification response has been recorded.",
            )
        )

        db.commit()
        db.refresh(incident)
        return incident

    except Exception:
        db.rollback()
        raise


def close_incident(
    db: Session,
    incident_id: int,
    admin_id: int,
    reason: str,
):
    """Close an incident and record the closure reason."""
    try:
        incident = db.scalar(
            select(Incident)
            .where(Incident.id == incident_id)
            .with_for_update()
        )

        if incident is None:
            raise HTTPException(status_code=404, detail="Incident not found")

        if incident.status in {"CLOSED", "RESOLVED"}:
            raise HTTPException(
                status_code=409,
                detail="This incident is already closed.",
            )

        incident.status = "CLOSED"

        db.add(
            IncidentStatusHistory(
                incident_id=incident.id,
                status="CLOSED",
                note=f"Case closed by admin {admin_id}: {reason}",
            )
        )

        db.add(
            Notification(
                user_id=incident.user_id,
                incident_id=incident.id,
                notification_type="CASE_CLOSED",
                message=f"Your incident has been closed. Reason: {reason}",
            )
        )

        db.commit()
        db.refresh(incident)
        return incident

    except Exception:
        db.rollback()
        raise