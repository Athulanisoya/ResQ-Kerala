from datetime import datetime, timezone
from typing import Literal

from pydantic import Field, field_validator, model_validator

from backend.schemas.common import InputModel, OutputModel


AlertLevel = Literal["YELLOW", "ORANGE", "RED"]
AlertStatus = Literal["ACTIVE", "SCHEDULED", "EXPIRED"]


def aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Include a timezone in alert dates, for example +05:30 or Z.")
    return value.astimezone(timezone.utc)


class AlertCreate(InputModel):
    title: str = Field(min_length=3, max_length=160)
    message: str = Field(min_length=5, max_length=5000)
    level: AlertLevel
    place_id: str = Field(min_length=1, max_length=100)
    starts_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime

    @field_validator("starts_at", "expires_at")
    @classmethod
    def dates_are_utc(cls, value):
        return aware_utc(value)

    @model_validator(mode="after")
    def valid_window(self):
        if self.expires_at <= self.starts_at:
            raise ValueError("The alert expiry must be after its start.")
        return self


class AlertUpdate(InputModel):
    title: str | None = Field(default=None, min_length=3, max_length=160)
    message: str | None = Field(default=None, min_length=5, max_length=5000)
    level: AlertLevel | None = None
    place_id: str | None = Field(default=None, min_length=1, max_length=100)
    starts_at: datetime | None = None
    expires_at: datetime | None = None

    @field_validator("*", mode="before")
    @classmethod
    def provided_values_cannot_be_null(cls, value):
        if value is None:
            raise ValueError("Alert fields cannot be null.")
        return value

    @field_validator("starts_at", "expires_at")
    @classmethod
    def dates_are_utc(cls, value):
        return aware_utc(value)

    @model_validator(mode="after")
    def at_least_one_change(self):
        if not self.model_fields_set:
            raise ValueError("Provide at least one alert field to update.")
        return self


class AlertResponse(OutputModel):
    id: int
    title: str
    message: str
    level: AlertLevel
    place_id: str
    place_name: str
    place_kind: Literal["district", "locality"]
    district_id: str
    district: str
    created_by_id: int
    starts_at: datetime
    expires_at: datetime
    expired_at: datetime | None
    created_at: datetime
    updated_at: datetime
    status: AlertStatus


class AlertMatchRequest(InputModel):
    message: str = Field(min_length=2, max_length=5000)
    reported_location: str | None = Field(default=None, max_length=255)

    @field_validator("reported_location")
    @classmethod
    def blank_location_is_none(cls, value):
        return value or None


class AlertMatch(OutputModel):
    status: Literal["MATCH", "NO_MATCH", "UNCERTAIN"]
    reason: str
    alerts: list[AlertResponse]
    checked_at: datetime
