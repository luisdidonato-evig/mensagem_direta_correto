import uuid
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class WabaConnectionStatus(StrEnum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTED = "CONNECTED"
    ERROR = "ERROR"


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255))
    timezone: Mapped[str] = mapped_column(String(64), default="America/Sao_Paulo")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    waba_connection: Mapped["WabaConnection | None"] = relationship(
        "WabaConnection", back_populates="organization", uselist=False
    )


class WabaConnection(Base):
    __tablename__ = "waba_connections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id"), unique=True, index=True
    )
    business_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    waba_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    phone_number_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    api_version: Mapped[str] = mapped_column(String(16), default="v23.0")
    # Armazena envelope Fernet; a chave vem de PII_HASH_SECRET no MVP.
    access_token: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[WabaConnectionStatus] = mapped_column(
        Enum(WabaConnectionStatus), default=WabaConnectionStatus.DISCONNECTED
    )
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    organization: Mapped["Organization"] = relationship(
        "Organization", back_populates="waba_connection"
    )
