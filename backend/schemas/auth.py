from pydantic import ConfigDict, EmailStr, Field, StrictStr, field_validator

from ..models import Role
from .common import InputModel, OutputModel


class RegisterRequest(InputModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)
    full_name: StrictStr = Field(min_length=3, max_length=100)
    email: EmailStr = Field(max_length=254)
    password: StrictStr = Field(min_length=10, max_length=128)

    @field_validator("full_name", mode="before")
    @classmethod
    def normalize_name(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value):
        return value.strip().lower() if isinstance(value, str) else value


class LoginRequest(InputModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)
    email: EmailStr = Field(max_length=254)
    password: StrictStr = Field(min_length=10, max_length=128)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value):
        return value.strip().lower() if isinstance(value, str) else value


class UserResponse(OutputModel):
    id: int
    full_name: str
    email: str
    role: Role
    team_id: int | None


class AuthResponse(OutputModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse
