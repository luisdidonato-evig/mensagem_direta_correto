"""Initial direct messages schema.

Revision ID: 20260921_0001
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260921_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

template_category = sa.Enum("MARKETING", "UTILITY", name="templatecategory")
template_status = sa.Enum(
    "DRAFT", "PENDING", "APPROVED", "REJECTED", "PAUSED", "DISABLED", name="templatestatus"
)
campaign_status = sa.Enum(
    "DRAFT",
    "VALIDATED",
    "SCHEDULED",
    "QUEUED",
    "SENDING",
    "COMPLETED",
    "PARTIAL_FAILURE",
    "CANCELLED",
    "FAILED",
    name="campaignstatus",
)
recipient_status = sa.Enum(
    "SELECTED",
    "SUPPRESSED",
    "ACCEPTED",
    "SENT",
    "DELIVERED",
    "READ",
    "REPLIED",
    "FAILED",
    "OPTED_OUT",
    name="recipientstatus",
)


def upgrade() -> None:
    op.create_table(
        "message_templates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("meta_template_id", sa.String(128)),
        sa.Column("name", sa.String(512), nullable=False),
        sa.Column("display_name", sa.String(512), nullable=False),
        sa.Column("language", sa.String(16), nullable=False),
        sa.Column("category", template_category, nullable=False),
        sa.Column("status", template_status, nullable=False),
        sa.Column("components", sa.JSON(), nullable=False),
        sa.Column("variable_schema", sa.JSON(), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("rejection_reason", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("meta_template_id", "language", name="uq_meta_template_language"),
    )
    op.create_index("ix_message_templates_name", "message_templates", ["name"])

    op.create_table(
        "campaigns",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("product", sa.String(255)),
        sa.Column("template_id", sa.String(36), nullable=False),
        sa.Column("audience_rules", sa.JSON(), nullable=False),
        sa.Column("variable_mapping", sa.JSON(), nullable=False),
        sa.Column("status", campaign_status, nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True)),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["template_id"], ["message_templates.id"]),
    )
    op.create_table(
        "campaign_recipients",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("campaign_id", sa.String(36), nullable=False),
        sa.Column("external_contact_id", sa.String(128), nullable=False),
        sa.Column("phone_e164", sa.String(32), nullable=False),
        sa.Column("variables", sa.JSON(), nullable=False),
        sa.Column("eligibility_snapshot", sa.JSON(), nullable=False),
        sa.Column("status", recipient_status, nullable=False),
        sa.Column("wamid", sa.String(512)),
        sa.Column("failure_code", sa.String(128)),
        sa.Column("failure_detail", sa.Text()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"]),
        sa.UniqueConstraint("campaign_id", "external_contact_id", name="uq_campaign_contact"),
    )
    op.create_index("ix_campaign_recipients_campaign_id", "campaign_recipients", ["campaign_id"])
    op.create_index("ix_campaign_recipients_wamid", "campaign_recipients", ["wamid"])

    op.create_table(
        "consents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("external_contact_id", sa.String(128), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_consents_external_contact_id", "consents", ["external_contact_id"])
    op.create_table(
        "opt_outs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("phone_hash", sa.String(64), nullable=False),
        sa.Column("scope", sa.String(32), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("reason", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("phone_hash", "scope", name="uq_opt_out_phone_scope"),
    )
    op.create_index("ix_opt_outs_phone_hash", "opt_outs", ["phone_hash"])

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("actor", sa.String(128), nullable=False),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("resource_type", sa.String(64), nullable=False),
        sa.Column("resource_id", sa.String(128), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])
    op.create_index("ix_audit_logs_resource_id", "audit_logs", ["resource_id"])
    op.create_table(
        "webhook_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("event_key", sa.String(64), nullable=False, unique=True),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("payload", sa.JSON()),
        sa.Column("error", sa.Text()),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_webhook_events_event_key", "webhook_events", ["event_key"])
    op.create_index("ix_webhook_events_event_type", "webhook_events", ["event_type"])


def downgrade() -> None:
    op.drop_table("webhook_events")
    op.drop_table("audit_logs")
    op.drop_table("opt_outs")
    op.drop_table("consents")
    op.drop_table("campaign_recipients")
    op.drop_table("campaigns")
    op.drop_table("message_templates")
