"""dispatch leases and durable handoff outbox

Revision ID: 20260921_0008
Revises: 20260921_0007
"""

import sqlalchemy as sa
from alembic import op

revision = "20260921_0008"
down_revision = "20260921_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("campaigns") as batch:
        batch.add_column(sa.Column("dispatch_lease_owner", sa.String(36), nullable=True))
        batch.add_column(
            sa.Column("dispatch_lease_until", sa.DateTime(timezone=True), nullable=True)
        )
        batch.create_index("ix_campaigns_dispatch_lease_until", ["dispatch_lease_until"])

    op.create_table(
        "handoff_deliveries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("event_key", sa.String(128), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("event_key", name="uq_handoff_delivery_event_key"),
    )
    op.create_index("ix_handoff_deliveries_event_key", "handoff_deliveries", ["event_key"])
    op.create_index("ix_handoff_deliveries_status", "handoff_deliveries", ["status"])
    op.create_index(
        "ix_handoff_deliveries_next_attempt_at", "handoff_deliveries", ["next_attempt_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_handoff_deliveries_next_attempt_at", table_name="handoff_deliveries")
    op.drop_index("ix_handoff_deliveries_status", table_name="handoff_deliveries")
    op.drop_index("ix_handoff_deliveries_event_key", table_name="handoff_deliveries")
    op.drop_table("handoff_deliveries")
    with op.batch_alter_table("campaigns") as batch:
        batch.drop_index("ix_campaigns_dispatch_lease_until")
        batch.drop_column("dispatch_lease_until")
        batch.drop_column("dispatch_lease_owner")
