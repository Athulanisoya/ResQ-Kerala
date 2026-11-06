from datetime import datetime, timezone
import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from backend.config import get_settings
from backend.database.connection import get_db
from backend.models import Role, User
from backend.models.automation import AutomationPolicy, AutomationRuntime
from backend.services.automation_policy_service import get_policy
from backend.utils.permissions import require_roles


router = APIRouter(prefix="/api/admin/automations", tags=["Automation settings"])
admin = require_roles(Role.ADMIN)


class PolicyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stale_minutes: int = Field(ge=1, le=1440, strict=True)
    reminder_minutes: int = Field(ge=5, le=1440, strict=True)
    escalation_minutes: int = Field(ge=2, le=10080, strict=True)
    waitlist_offer_minutes: int = Field(ge=1, le=1440, strict=True)
    expected_version: int = Field(ge=0, strict=True)

    @model_validator(mode="after")
    def ordered(self):
        if self.escalation_minutes <= self.stale_minutes:
            raise ValueError("Admin escalation must follow the first stale-capacity reminder")
        return self


def policy_view(policy):
    return {key: getattr(policy, key) for key in ("stale_minutes", "reminder_minutes", "escalation_minutes", "waitlist_offer_minutes", "version", "updated_at")}


@router.get("")
def view(db: Session = Depends(get_db), _actor: User = Depends(admin)):
    state = db.get(AutomationRuntime, 1)
    return {"policy": policy_view(get_policy(db)), "enabled": get_settings().automation_enabled,
            "poll_seconds": get_settings().automation_poll_seconds,
            "runtime": {"checked_at": state.checked_at, "last_success_at": state.last_success_at,
                        "has_error": state.has_error, "jobs": json.loads(state.summary)} if state else None}


@router.put("")
def save(data: PolicyInput, db: Session = Depends(get_db), actor: User = Depends(admin)):
    row = db.scalar(select(AutomationPolicy).where(AutomationPolicy.id == 1).with_for_update().execution_options(populate_existing=True))
    if (row.version if row else 0) != data.expected_version:
        raise HTTPException(409, "Automation settings changed. Reload before saving.")
    values = data.model_dump(exclude={"expected_version"})
    if row is None:
        row = AutomationPolicy(id=1, **values, updated_by=actor.id, version=1)
        db.add(row)
    else:
        for name, value in values.items():
            setattr(row, name, value)
        row.version += 1
        row.updated_by = actor.id
        row.updated_at = datetime.now(timezone.utc)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Automation settings changed. Reload before saving.") from None
    return policy_view(row)


@router.post("/run")
def run(db: Session = Depends(get_db), _actor: User = Depends(admin)):
    from backend.services.automation_runner import run_cycle
    factory = sessionmaker(bind=db.get_bind(), autoflush=False, expire_on_commit=False)
    return run_cycle(factory)
