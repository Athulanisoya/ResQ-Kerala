from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------
# Schema used when creating an incident
# ---------------------------------------------------------

class IncidentCreate(BaseModel):

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

    status: str

    created_at: datetime

    updated_at: datetime

    class Config:
        from_attributes = True


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