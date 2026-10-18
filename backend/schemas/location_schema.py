"""Auditable place matches for Athul's Week 2 ingestion pipeline."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Place(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    name: str
    district_id: str
    district: str
    kind: Literal["district", "locality"]
    aliases: list[str] = Field(default_factory=list)
    source: str


class LocationExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["RESOLVED", "UNCERTAIN"]
    place: Place | None = None
    candidates: list[Place] = Field(default_factory=list)
    matched_text: list[str] = Field(default_factory=list)
    reason: str
