from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator


Skill = Literal['shelter_support', 'food_distribution', 'logistics', 'translation', 'community_support', 'trained_first_aid']


class VolunteerInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    expected_version: int = Field(ge=0, strict=True)
    district_id: str = Field(min_length=1, max_length=100)
    locality_id: str | None = Field(default=None, max_length=100)
    ward: str = Field(min_length=1, max_length=120)
    skills: list[Skill] = Field(min_length=1, max_length=6)
    availability: str = Field(min_length=5, max_length=1000)
    consent: Literal[True]

    @field_validator('locality_id')
    @classmethod
    def blank_locality(cls, value):
        return value or None


class VersionNote(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    expected_version: int = Field(ge=1, strict=True)
    note: str = Field(min_length=3, max_length=1000)


class ApplicationReview(VersionNote):
    decision: Literal['APPROVED', 'REJECTED', 'SUSPENDED']


class ShiftCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    title: str = Field(min_length=3, max_length=160)
    kind: Literal['SHELTER', 'RELIEF', 'FIELD_SUPPORT']
    place_id: str = Field(min_length=1, max_length=100)
    shelter_id: int | None = Field(default=None, gt=0, strict=True)
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    slots: int = Field(ge=1, le=1000, strict=True)
    required_skills: list[Skill] = Field(default_factory=list, max_length=6)
    instructions: str = Field(default='', max_length=2000)

    @model_validator(mode='after')
    def interval(self):
        if self.ends_at <= self.starts_at:
            raise ValueError('The shift must end after it starts.')
        if (self.ends_at - self.starts_at).total_seconds() > 86400:
            raise ValueError('One shift may last at most 24 hours.')
        return self


class ShiftUpdate(ShiftCreate):
    expected_version: int = Field(ge=1, strict=True)


class ShiftSignup(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_version: int = Field(ge=1, strict=True)


class Attendance(VersionNote):
    status: Literal['CHECKED_IN', 'COMPLETED', 'NO_SHOW']
