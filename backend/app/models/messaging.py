import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ContactMessagingState(Base):
    __tablename__ = "contact_messaging_states"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "phone_hash", name="uq_contact_messaging_org_phone"
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id"), index=True
    )
    phone_hash: Mapped[str] = mapped_column(String(64), index=True)
    consecutive_template_sends: Mapped[int] = mapped_column(Integer, default=0)
    reserved_template_sends: Mapped[int] = mapped_column(Integer, default=0)
    last_outbound_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_inbound_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
