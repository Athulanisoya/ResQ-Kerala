from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .alert_schema import AlertMatch
from .location_schema import LocationExtraction


class LocationAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    use_agent: bool = False


class ToolCallEvidence(BaseModel):
    name: str
    arguments: dict = Field(default_factory=dict)
    output: dict


class LocationAnalysisResult(BaseModel):
    extraction: LocationExtraction
    alert_match: AlertMatch
    mode: Literal["deterministic", "agent", "fallback"]
    model: str | None = None
    tool_calls: list[ToolCallEvidence] = Field(default_factory=list)
    warning: str | None = None


class LocationAnalysisResponse(LocationAnalysisResult):
    model_config = ConfigDict(from_attributes=True)
    id: int
    incident_id: int
    created_at: datetime
