from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    incident_id: int
    summary: str = Field(max_length=1200)
    method: Literal["local_extractive_v1"]
    method_label: Literal["Local extractive draft"] = "Local extractive draft"
    input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_by_id: int
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def timestamp_has_timezone(cls, value: datetime) -> datetime:
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
