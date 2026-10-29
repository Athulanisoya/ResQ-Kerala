from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import select

from backend.models import IncidentStatusHistory, Team
from backend.models.relief import ReliefRequest

from backend.utils.permissions import (
    require_assigned_service_team,
    require_incident_access,
)


def add_service_history(db, incident, note):
    incident.updated_at = datetime.utcnow()

    db.add(
        IncidentStatusHistory(
            incident_id=incident.id,
            status=incident.status,
            note=note,
        )
    )


def accept_task(db, incident_id, user):
    incident = require_incident_access(
        db,
        incident_id,
        user,
        lock=True,
    )

    require_assigned_service_team(
        db,
        incident,
        user,
        {"rescue", "relief"},
    )

    if incident.status != "ASSIGNED":
        raise HTTPException(
            409,
            "Only an assigned task can be accepted",
        )

    from backend.services.operations_service import _current_task, _record_progress, _notify
    task = _current_task(db, incident)
    task.accepted_at = datetime.utcnow()
    _record_progress(db, incident, task, user, "ACCEPTED",
                     f"Task accepted by team {user.team_id}; user {user.id}")
    db.flush()
    _notify(db, incident, "Task accepted", f"{task.team_name} accepted the task.",
            event_key=f"task:{task.id}:accepted")
    db.commit()

    return incident


def update_progress(db, incident_id, user, data):
    incident = require_incident_access(
        db,
        incident_id,
        user,
        lock=True,
    )

    team = require_assigned_service_team(
        db,
        incident,
        user,
        {"rescue", "relief"},
    )

    allowed = {
        "ACCEPTED": {"EN_ROUTE"},
        "TASK_ACCEPTED": {"EN_ROUTE"},
        "EN_ROUTE": {"IN_PROGRESS"},
    }

    if team.team_type.casefold() == "rescue":
        allowed["IN_PROGRESS"] = {"RESCUE_COMPLETED"}

    else:
        allowed["IN_PROGRESS"] = {"RESOLVED"}

    if data.status not in allowed.get(
        incident.status,
        set(),
    ):
        raise HTTPException(
            409,
            "Follow acceptance, travel and progress in order",
        )

    if data.status == "RESOLVED":
        requests = db.scalars(
            select(ReliefRequest).where(
                ReliefRequest.incident_id == incident.id
            )
        ).all()

        from backend.services.operations_service import unfinished_relief
        if not requests or unfinished_relief(db, incident.id):
            raise HTTPException(
                409,
                "Complete all relief requests before resolving",
            )

    from backend.services.operations_service import _current_task, _record_progress, _notify, release_team_if_idle
    task = _current_task(db, incident)
    _record_progress(db, incident, task, user, data.status, f"User {user.id}: {data.note}")
    if data.status == "RESOLVED":
        task.active = False
        task.ended_at = datetime.utcnow()
        db.flush()
        release_team_if_idle(db, team.id)
    db.flush()
    _notify(db, incident, "Response progress updated", f"{task.team_name}: {data.status.replace('_', ' ').lower()}.",
            event_key=f"task:{task.id}:{data.status}")
    db.commit()

    return incident


def handoff_to_relief(db, incident_id, user, data):
    incident = require_incident_access(
        db,
        incident_id,
        user,
        lock=True,
    )

    if (
        incident.status != "RESCUE_COMPLETED"
        or incident.assigned_team_id is None
    ):
        raise HTTPException(
            409,
            "Complete rescue before a relief handoff",
        )

    pending = db.scalar(
        select(ReliefRequest.id).where(
            ReliefRequest.incident_id == incident.id,
            ReliefRequest.fulfilled < ReliefRequest.quantity,
        )
    )

    if pending is None:
        raise HTTPException(
            409,
            "Create an outstanding relief request first",
        )

    ids = sorted(
        {
            incident.assigned_team_id,
            data.team_id,
        }
    )

    teams = {
        team.id: team
        for team in db.scalars(
            select(Team)
            .where(Team.id.in_(ids))
            .order_by(Team.id)
            .with_for_update()
        )
    }

    old = teams.get(incident.assigned_team_id)

    new = teams.get(data.team_id)

    if new is None:
        raise HTTPException(
            404,
            "Relief team not found",
        )

    if (
        old is None
        or old.team_type.casefold() != "rescue"
    ):
        raise HTTPException(
            409,
            "Current assignment must be a rescue team",
        )

    if (
        new.team_type.casefold() != "relief"
        or new.status != "AVAILABLE"
    ):
        raise HTTPException(
            409,
            "Choose an available Relief team",
        )

    from backend.models.operations import IncidentTaskEvent
    from backend.services.operations_service import _current_task, capture_assignment, release_team_if_idle, _notify
    task = _current_task(db, incident)
    task.status = "HANDED_OFF"
    task.active = False
    task.ended_at = datetime.utcnow()
    db.add(IncidentTaskEvent(task_id=task.id, status="HANDED_OFF", note=data.note, actor_user_id=user.id))
    new.status = "BUSY"
    incident.assigned_team_id = new.id
    incident.status = "ASSIGNED"

    add_service_history(
        db,
        incident,
        (
            f"Admin {user.id}: handoff {old.id} to {new.id}. "
            f"{data.note}"
        ),
    )

    successor_task = capture_assignment(db, incident, new, data.note, user.id)
    db.flush()
    release_team_if_idle(db, old.id)
    _notify(db, incident, "Response handoff completed", f"{old.name} handed off to {new.name}.",
            event_key=f"task:{successor_task.id}:handoff")
    db.commit()

    return incident
