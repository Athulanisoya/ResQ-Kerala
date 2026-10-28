from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

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
    app_version: str = "2.0.0-integrated"
    database_schema: str = Field(default="resq_week1", pattern=r"^[a-z][a-z0-9_]{0,62}$")
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = Field(default="gemma4:e4b-it-q4_K_M", min_length=1, max_length=100)
    agent_timeout_seconds: float = Field(default=120, ge=1, le=300)
    agent_max_turns: int = Field(default=6, ge=2, le=12)

    @field_validator("ollama_base_url")
    @classmethod
    def validate_ollama_url(cls, value: str) -> str:
        """This setup sends model requests only to the local Ollama server."""
        parsed = urlsplit(value)
        if (parsed.scheme not in {"http", "https"}
                or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
                or parsed.username is not None or parsed.password is not None
                or parsed.path not in {"", "/"} or parsed.query or parsed.fragment):
            raise ValueError("OLLAMA_BASE_URL must be a local http(s) server URL without credentials or a path")
        # Accessing port rejects malformed values before making a request.
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            raise ValueError("OLLAMA_BASE_URL must use a valid server port")
        return value.rstrip("/")

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
