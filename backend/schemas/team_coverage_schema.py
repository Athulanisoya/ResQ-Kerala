from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


Capability = Literal["water_rescue", "evacuation", "medical_support", "food_distribution", "shelter_support", "field_assessment"]
TeamType = Literal["Rescue", "Relief", "Shelter", "Investigation"]


class TeamCoverageUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_version: int = Field(ge=0, strict=True)
    area_ids: list[str] = Field(default_factory=list, max_length=114)
    capabilities: list[Capability] = Field(default_factory=list, max_length=6)
    note: str = Field(default="", max_length=500)
