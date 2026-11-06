"""Remind staff about stale capacity confirmations, without changing capacity."""
from datetime import datetime, timedelta, timezone
import hashlib
from urllib.parse import urlencode

from sqlalchemy import select

from backend.models import Role, Team, User
from backend.models.automation import ShelterReminderState
from backend.models.shelter import Shelter
from backend.services.automation_notifications import notify_user
from backend.services.automation_policy_service import get_policy


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def process_shelter_reminders(db, *, now=None):
    now = utc(now or datetime.now(timezone.utc))
    policy = get_policy(db)
    counts = {"shelters_checked": 0, "staff_notifications": 0, "admin_notifications": 0}
    admins = list(db.scalars(select(User.id).where(User.active.is_(True), User.role == Role.ADMIN)))
    for shelter in db.scalars(select(Shelter).where(Shelter.status != "CLOSED").order_by(Shelter.id)
                              .with_for_update().execution_options(populate_existing=True)):
        counts["shelters_checked"] += 1
        confirmed = utc(shelter.capacity_confirmed_at) if shelter.capacity_confirmed_at else None
        if confirmed and confirmed > now + timedelta(minutes=5):
            confirmed = None
        key = confirmed.isoformat() if confirmed else "unknown"
        state = db.get(ShelterReminderState, shelter.id)
        if state and state.confirmation_key != key:
            state.confirmation_key = key
            state.last_notified_at = state.last_escalated_at = None
        age = now - confirmed if confirmed else None
        if age is not None and age < timedelta(minutes=policy.stale_minutes):
            continue
        if state is None:
            state = ShelterReminderState(shelter_id=shelter.id, confirmation_key=key, sequence=0)
            db.add(state)
        team = db.get(Team, shelter.team_id) if shelter.team_id else None
        staff = list(db.scalars(select(User.id).where(User.active.is_(True), User.role == Role.RESPONSE_TEAM,
                                  User.team_id == team.id))) if team and team.team_type.casefold() == "shelter" and team.status != "OFFLINE" else []
        regular_due = state.last_notified_at is None or now - utc(state.last_notified_at) >= timedelta(minutes=policy.reminder_minutes)
        escalate = not staff or confirmed is None or age >= timedelta(minutes=policy.escalation_minutes)
        admin_due = escalate and (state.last_escalated_at is None or now - utc(state.last_escalated_at) >= timedelta(minutes=policy.reminder_minutes))
        if not regular_due and not admin_due:
            continue
        state.sequence += 1
        episode = hashlib.sha256(key.encode()).hexdigest()[:16]
        message = (f"{shelter.name}: capacity confirmation time is unknown. " if confirmed is None else
                   f"{shelter.name}: staff last confirmed capacity at {confirmed.strftime('%d %b %Y %H:%M UTC')}. ")
        message += "Review the real head count and reserved/held spaces, then save a capacity update. Booking activity does not confirm capacity."
        target = "/shelters?" + urlencode({"q": shelter.name})
        event = f"capacity-reminder:{shelter.id}:{episode}:{state.sequence}"
        if regular_due:
            for user_id in staff:
                if notify_user(db, user_id, "Shelter capacity needs confirmation", message, event + ":staff", target):
                    counts["staff_notifications"] += 1
            state.last_notified_at = now
        if admin_due:
            for user_id in admins:
                if notify_user(db, user_id, "Shelter capacity review overdue", message, event + ":admin", target):
                    counts["admin_notifications"] += 1
            state.last_escalated_at = now
    db.flush()
    return counts
