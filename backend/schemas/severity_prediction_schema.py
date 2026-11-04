from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SeverityDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    action: Literal["accept", "edit", "reject"]
    severity: Literal["LOW", "MEDIUM", "HIGH"] | None = None
    note: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_choice(self):
        if self.action == "edit" and self.severity is None:
            raise ValueError("Choose a reviewed severity when editing a suggestion.")
        if self.action != "edit" and self.severity is not None:
            raise ValueError("Only an edited suggestion accepts a replacement severity.")
        self.note = self.note or None
        return self


class SeverityDecisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    action: str
    reviewed_severity: str | None
    reviewed_by_user_id: int
    reviewed_at: datetime
    note: str | None
    previous_assessment: dict | None


class SeverityPredictionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    incident_id: int
    predicted_severity: Literal["LOW", "MEDIUM", "HIGH"]
    model_version: str
    input_hash: str
    requested_by_user_id: int
    created_at: datetime
    requires_manual_review: bool = True
    decision: SeverityDecisionResponse | None = None
