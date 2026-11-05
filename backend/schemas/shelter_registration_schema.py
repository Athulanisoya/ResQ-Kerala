from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from backend.schemas.common import InputModel


class ShelterRegistrationCreate(InputModel):
    party_size: int = Field(ge=1, le=1000, strict=True)
    origin_district: str = Field(min_length=2, max_length=100)
    origin_locality: str = Field(min_length=2, max_length=120)
    origin_latitude: float | None = Field(default=None, ge=-90, le=90)
    origin_longitude: float | None = Field(default=None, ge=-180, le=180)
    contact: str | None = Field(default=None, max_length=100)
    note: str | None = Field(default=None, max_length=500)
    request_key: UUID

    @model_validator(mode="after")
    def coordinates_together(self):
        if (self.origin_latitude is None) != (self.origin_longitude is None):
            raise ValueError("Supply both location coordinates or leave both empty.")
        self.contact = self.contact or None
        self.note = self.note or None
        return self


class ShelterRegistrationStatus(InputModel):
    status: Literal["ARRIVED", "CANCELLED", "DEPARTED"]
    expected_version: int = Field(ge=1, strict=True)
    note: str | None = Field(default=None, max_length=500)
