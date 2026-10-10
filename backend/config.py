from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=WORKSPACE_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str
    jwt_secret: SecretStr
    jwt_expire_minutes: int = Field(default=30, ge=5, le=1440)
    cors_origins: str = "http://localhost:5175,http://127.0.0.1:5175"
    allow_sqlite_for_tests: bool = False
    app_version: str = "1.0.0-athul-week1"
    database_schema: str = Field(default="athul_week1", pattern=r"^[a-z][a-z0-9_]{0,62}$")

    @field_validator("jwt_secret")
    @classmethod
    def validate_secret(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 32:
            raise ValueError("JWT_SECRET must contain at least 32 characters")
        return value

    @model_validator(mode="after")
    def validate_database(self) -> "Settings":
        if self.database_url.startswith("sqlite"):
            if not self.allow_sqlite_for_tests:
                raise ValueError("SQLite is restricted to tests; set ALLOW_SQLITE_FOR_TESTS=true")
        elif not self.database_url.startswith("postgresql+psycopg://"):
            raise ValueError("DATABASE_URL must use postgresql+psycopg://")
        return self

    @property
    def allowed_origins(self) -> list[str]:
        return [value.strip() for value in self.cors_origins.split(",") if value.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
