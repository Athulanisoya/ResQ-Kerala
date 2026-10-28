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


class ShelterCreate(ShelterCounts):
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