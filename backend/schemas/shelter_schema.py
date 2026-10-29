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
    source_name: str = Field(default="ResQ demo seed", min_length=2, max_length=200)
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
    district: str
    locality: str
    address: str
    capacity: int
    occupied: int
    status: ShelterStatus
    contact: str | None
    source_name: str
    updated_at: datetime
    available_capacity: int
    