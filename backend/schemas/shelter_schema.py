from datetime import datetime
from typing import Literal
from pydantic import Field, model_validator
from backend.schemas.common import InputModel, OutputModel
ShelterStatus = Literal["OPEN", "FULL", "CLOSED"]
class ShelterCreate(InputModel):
    name: str = Field(min_length=2, max_length=160)
    district: str = Field(min_length=2, max_length=100)
    locality: str = Field(min_length=2, max_length=120)
    address: str = Field(min_length=3, max_length=300)
    capacity: int = Field(ge=0)
    occupied: int = Field(default=0, ge=0)
    status: ShelterStatus = "OPEN"
    contact: str | None = Field(default=None, max_length=60)
    source_name: str | None = Field(default=None, min_length=2, max_length=200)
    @model_validator(mode="after")
    def validate_occupancy(self):
        if self.occupied > self.capacity:
            raise ValueError("Occupied spaces cannot exceed capacity.")
        if self.occupied == self.capacity and self.status == "OPEN":
            self.status = "FULL"
        return self
class ShelterResponse(OutputModel):
    id: int
    name: str
    district: str | None
    locality: str | None
    address: str | None
    capacity: int
    occupied: int
    status: ShelterStatus
    contact: str | None
    source_name: str | None
    updated_at: datetime | None
    available_capacity: int


from pydantic import Field, model_validator

from backend.schemas.relief_schema import ServiceInput


class ShelterCounts(ServiceInput):
    capacity: int = Field(
        gt=0,
        le=1000000,
        strict=True,
    )

    occupied: int = Field(
        ge=0,
        le=1000000,
        strict=True,
    )

    @model_validator(mode="after")
    def check_capacity(self):
        if self.occupied > self.capacity:
            raise ValueError(
                "Occupied places cannot exceed capacity"
            )

        return self


class ManagedShelterCreate(ShelterCounts):
    name: str = Field(
        min_length=3,
        max_length=100,
    )

    location: str = Field(
        min_length=2,
        max_length=255,
    )

    team_id: int = Field(gt=0)


class ShelterPatch(ShelterCounts):
    expected_version: int = Field(gt=0)

    note: str = Field(
        min_length=3,
        max_length=1000,
    )
