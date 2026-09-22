import uuid
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class CampaignStatus(StrEnum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    SCHEDULED = "SCHEDULED"
    QUEUED = "QUEUED"
    SENDING = "SENDING"
    COMPLETED = "COMPLETED"
    PARTIAL_FAILURE = "PARTIAL_FAILURE"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class RecipientStatus(StrEnum):
    SELECTED = "SELECTED"
    SUPPRESSED = "SUPPRESSED"
    ACCEPTED = "ACCEPTED"
    SENT = "SENT"
    DELIVERED = "DELIVERED"
    READ = "READ"
    REPLIED = "REPLIED"
    FAILED = "FAILED"
    OPTED_OUT = "OPTED_OUT"


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    product: Mapped[str | None] = mapped_column(String(255), nullable=True)
    template_id: Mapped[str] = mapped_column(ForeignKey("message_templates.id"))
    audience_rules: Mapped[dict] = mapped_column(JSON)
    variable_mapping: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[CampaignStatus] = mapped_column(
        Enum(CampaignStatus), default=CampaignStatus.DRAFT
    )
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), default="America/Sao_Paulo")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
    dispatch_lease_owner: Mapped[str | None] = mapped_column(String(36), nullable=True)
    dispatch_lease_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    template = relationship("MessageTemplate")
    recipients = relationship("CampaignRecipient", back_populates="campaign")


class CampaignRecipient(Base):
    __tablename__ = "campaign_recipients"
    __table_args__ = (
        UniqueConstraint("campaign_id", "external_contact_id", name="uq_campaign_contact"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id"), index=True)
    external_contact_id: Mapped[str] = mapped_column(String(128))
    # Conteúdo cifrado com Fernet; phone_hash permite correlação sem descriptografar.
    phone_e164: Mapped[str] = mapped_column(String(512))
    phone_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    variables: Mapped[dict] = mapped_column(JSON, default=dict)
    eligibility_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[RecipientStatus] = mapped_column(Enum(RecipientStatus))
    wamid: Mapped[str | None] = mapped_column(String(512), nullable=True, index=True)
    failure_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    failure_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    campaign = relationship("Campaign", back_populates="recipients")
