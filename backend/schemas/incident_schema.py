from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------------------------------------------------------
# Schema used when creating an incident
# ---------------------------------------------------------

class IncidentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    disaster_type: str = Field(default="Flood", min_length=2, max_length=50)

    message: str = Field(
        ...,
        min_length=5,
        max_length=5000
    )

    location: str = Field(
        ...,
        min_length=2,
        max_length=255
    )

    people_affected: Optional[int] = Field(
        default=None,
        ge=0,
        le=100000
    )

    help_required: Optional[str] = Field(
        default=None,
        max_length=255
    )

    @field_validator("help_required")
    @classmethod
    def empty_help_is_none(cls, value):
        return value or None


# ---------------------------------------------------------
# Schema returned when viewing an incident
# ---------------------------------------------------------

class IncidentResponse(BaseModel):

    id: int

    report_reference: str

    user_id: int

    message: str

    location: str

    people_affected: Optional[int] = None

    help_required: Optional[str] = None

    disaster_type: str

    assigned_team_id: Optional[int] = None

    status: str

    created_at: datetime

    updated_at: datetime

    class Config:
        from_attributes = True


class IncidentStatusUpdate(BaseModel):
    """resq's status endpoint, limited to the Week 1 admin review states."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    status: Literal["UNDER_REVIEW", "VERIFIED"]
    note: Optional[str] = Field(default=None, max_length=1000)


class TeamAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    incident_id: int = Field(gt=0)
    team_id: int = Field(gt=0)


class TeamResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    team_type: str
    available: bool


# ---------------------------------------------------------
# Schema returned for incident history
# ---------------------------------------------------------

class IncidentHistoryResponse(BaseModel):

    id: int

    incident_id: int

    status: str

    note: Optional[str] = None

    created_at: datetime

    class Config:
        from_attributes = True
