from dataclasses import dataclass

from backend.config import get_settings
from backend.models.automation import AutomationPolicy


@dataclass(frozen=True)
class DefaultPolicy:
    stale_minutes: int = 30
    reminder_minutes: int = 60
    escalation_minutes: int = 120
    waitlist_offer_minutes: int = 15
    version: int = 0
    updated_at: object = None


def get_policy(db):
    # Reading policy must not acquire a lock after a caller's shelter lock.
    return db.get(AutomationPolicy, 1) or DefaultPolicy(
        stale_minutes=get_settings().shelter_stale_after_minutes,
        escalation_minutes=max(120, get_settings().shelter_stale_after_minutes + 60))
