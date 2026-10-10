"""Only the account and authenticated-session entities needed for Athul's task."""
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from ..database.connection import Base


def utc_now():
    return datetime.now(timezone.utc)


class Role(str, Enum):
    CITIZEN = "citizen"
    ADMIN = "admin"
    RESPONSE_TEAM = "response_team"


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(SAEnum(Role, values_callable=lambda values: [item.value for item in values], native_enum=False, create_constraint=True), default=Role.CITIZEN)
    # Preserve the account response contract for integration with the shared app.
    # Team membership/operations are managed by other members and are absent here.
    team_id: Mapped[int | None] = mapped_column(nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class TokenSession(Base):
    __tablename__ = "token_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
