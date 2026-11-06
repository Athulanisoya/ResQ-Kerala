from pydantic import Field

from backend.schemas.common import InputModel
from backend.schemas.shelter_registration_schema import ShelterRegistrationCreate


class ShelterWaitlistCreate(ShelterRegistrationCreate):
    pass


class ShelterWaitlistAction(InputModel):
    expected_version: int = Field(ge=1, strict=True)
